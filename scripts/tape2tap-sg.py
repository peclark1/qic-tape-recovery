#!/usr/bin/env python3
"""Capture variable-record SCSI tape from its current position on Linux."""

import argparse
import ctypes as c
import hashlib
import json
import os
import struct
from pathlib import Path

BUFFER = 32768


class SgIo(c.Structure):
    _fields_ = [
        ("interface_id", c.c_int), ("dxfer_direction", c.c_int),
        ("cmd_len", c.c_ubyte), ("mx_sb_len", c.c_ubyte),
        ("iovec_count", c.c_ushort), ("dxfer_len", c.c_uint),
        ("dxferp", c.c_void_p), ("cmdp", c.c_void_p),
        ("sbp", c.c_void_p), ("timeout", c.c_uint),
        ("flags", c.c_uint), ("pack_id", c.c_int),
        ("usr_ptr", c.c_void_p), ("status", c.c_ubyte),
        ("masked_status", c.c_ubyte), ("msg_status", c.c_ubyte),
        ("sb_len_wr", c.c_ubyte), ("host_status", c.c_ushort),
        ("driver_status", c.c_ushort), ("resid", c.c_int),
        ("duration", c.c_uint), ("info", c.c_uint),
    ]


def scsi(fd, cdb, size, outgoing=None):
    libc = c.CDLL(None, use_errno=True)
    libc.ioctl.argtypes = (c.c_int, c.c_ulong, c.c_void_p)
    cmd = c.create_string_buffer(cdb)
    data = c.create_string_buffer(size)
    if outgoing is not None:
        data.raw = outgoing
    sense = c.create_string_buffer(64)
    io = SgIo(ord("S"), -2 if outgoing is not None else -3,
              len(cdb), 64, 0, size, c.addressof(data),
              c.addressof(cmd), c.addressof(sense), 180000)
    if libc.ioctl(fd, 0x2285, c.byref(io)) < 0:
        err = c.get_errno()
        raise OSError(err, os.strerror(err))
    payload = data.raw[:size - io.resid] if 0 <= io.resid <= size else b""
    return io, payload, sense.raw[:io.sb_len_wr]


def read_record(fd):
    return scsi(fd, bytes.fromhex("08 02 00 80 00 00"), BUFFER)


def configure_retries(fd, count):
    def checked(cdb, size, outgoing=None):
        io, payload, sense = scsi(fd, bytes(cdb), size, outgoing)
        if io.status or io.host_status or io.driver_status or not 0 <= io.resid <= size:
            raise OSError(f"SCSI command {cdb[0]:02x} failed: status={io.status:#x} "
                          f"host={io.host_status:#x} driver={io.driver_status:#x} "
                          f"resid={io.resid} sense={sense.hex()}")
        if outgoing is not None and io.resid:
            raise OSError("Incomplete MODE SELECT transfer")
        return payload

    inquiry = checked([0x12, 0, 0, 0, 36, 0], 36)
    if (len(inquiry) < 32 or inquiry[0] & 31 != 1
            or inquiry[8:16].strip() != b"TANDBERG"
            or inquiry[16:32].strip() != b"TDC 4100"):
        raise OSError("--read-retries is supported only on the Tandberg TDC 4100")

    def recovery_page(control):
        page = checked([0x1a, 8, 1 | control << 6, 0, 16, 0], 16)
        if len(page) != 16 or page[3] or page[4] & 0x7f != 1 or page[5] != 10:
            raise OSError("Unexpected TDC 4100 error recovery page")
        return page

    current = recovery_page(0)
    previous = current[7]
    if previous != count:
        if recovery_page(1)[7] != 0xff:
            raise OSError("Drive does not report a writable read retry count")
        params = bytearray(current)
        params[:4] = bytes((0, 0, current[2] & 0x70, 0))
        params[4] &= 0x7f
        params[7] = count
        checked([0x15, 0x10, 0, 0, 16, 0], 16, bytes(params))
        verified = recovery_page(0)
        if verified[6:] != params[6:]:
            raise OSError("MODE SELECT readback did not match the requested recovery page")
    return previous


def word(value):
    return struct.pack("<I", value)


def capture(reader, tap, journal, directory, file_number):
    good = suspect = empty = in_file = reads = 0
    while True:
        io, payload, sense = reader()
        reads += 1
        event = dict(read=reads, file=file_number, offset=tap.tell(),
                     bytes=len(payload), status=io.status, host=io.host_status,
                     driver=io.driver_status, residual=io.resid, sense=sense.hex())
        fixed = len(sense) >= 14 and (sense[0] & 0x7f) == 0x70
        check = (io.status == 2 and not io.host_status and fixed
                 and io.driver_status in (0, 8))
        key = sense[2] & 15 if check else None
        stop = None
        if io.host_status or not 0 <= io.resid <= BUFFER:
            kind = "transport_or_residual_error"
            stop = 1
        elif io.status == 0 and not io.driver_status and payload:
            kind = "record"
            good += 1
            in_file += 1
            empty = 0
        elif key == 0 and sense[2] & 0x80 and sense[12:14] == b"\0\1" and not payload:
            kind = "filemark"
            tap.write(word(0))
            print(f"File {file_number}: {in_file} records, filemark", flush=True)
            file_number += 1
            in_file = empty = 0
        elif key == 8 and sense[12:14] == b"\0\5" and not payload:
            kind = "end_of_data"
            tap.write(word(0xffffffff))
            stop = 3 if suspect else 0
        elif key == 3:
            kind = "suspect_record" if payload else "possible_gap"
            suspect += 1
            in_file += bool(payload)
            empty = 0 if payload else empty + 1
            if empty >= 3:
                stop = 1
        else:
            kind = "unexpected_result"
            stop = 1

        if kind in ("record", "suspect_record"):
            marker = word(len(payload) | (0x80000000 if kind == "suspect_record" else 0))
            tap.write(marker + payload + (b"\0" if len(payload) % 2 else b"") + marker)
        if payload and kind != "record":
            sidecar = directory / f"read-{reads:09d}.bin"
            sidecar.write_bytes(payload)
            event["payload_file"] = sidecar.name
        event["event"] = kind
        print(json.dumps(event), file=journal, flush=True)
        if kind in ("suspect_record", "possible_gap"):
            print(f"File {file_number}, read {reads}: {kind}, {len(payload)} bytes", flush=True)
        if stop is not None:
            print(f"{kind}: {good} good records, {suspect} medium errors, {reads} reads")
            return stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="new capture directory")
    parser.add_argument("--device", default="/dev/sg1")
    parser.add_argument("--start-file", type=int, default=0,
                        help="label for current file, does not move the tape")
    parser.add_argument("--read-retries", type=int, metavar="1-24",
                        help="set and verify the TDC 4100 session read retry limit")
    args = parser.parse_args()
    if args.read_retries is not None and not 1 <= args.read_retries <= 24:
        parser.error("--read-retries must be between 1 and 24")
    if args.start_file < 0:
        parser.error("--start-file must be nonnegative")
    args.directory.mkdir()
    image = args.directory / "capture.tap"
    result = 1
    with image.open("xb") as tap, (args.directory / "capture.jsonl").open("x") as log:
        print(json.dumps(dict(event="start", device=args.device, file=args.start_file,
                              buffer=BUFFER)), file=log, flush=True)
        try:
            fd = os.open(args.device, os.O_RDWR if args.read_retries is not None else os.O_RDONLY)
            try:
                if args.read_retries is not None:
                    previous = configure_retries(fd, args.read_retries)
                    print(f"Drive read retries: {previous} -> {args.read_retries}", flush=True)
                    print(json.dumps(dict(event="read_retries", previous=previous,
                                          current=args.read_retries)), file=log, flush=True)
                result = capture(lambda: read_record(fd), tap, log, args.directory, args.start_file)
            finally:
                os.close(fd)
        except (OSError, KeyboardInterrupt) as error:
            print(json.dumps(dict(event="interrupted" if isinstance(error, KeyboardInterrupt)
                                  else "error", detail=str(error))), file=log, flush=True)
            print(f"Capture stopped: {error or 'interrupted'}")
            result = 130 if isinstance(error, KeyboardInterrupt) else 1
        finally:
            tap.flush()
            os.fsync(tap.fileno())
    with image.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    (args.directory / "SHA256SUMS").write_text(f"{digest}  {image.name}\n")
    return result


if __name__ == "__main__":
    raise SystemExit(main())