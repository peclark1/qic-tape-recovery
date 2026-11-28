#!/usr/bin/env python3
"""Audit IBM CVTSC string compression in IBM-labelled SIMH tapes."""
import argparse
from collections import Counter
import json

from recovery_toolkit import END, ERR, digest, frames, label

BLOCK_SIZE = 24576


class SCBError(ValueError):
    def __init__(self, offset, produced, reason):
        super().__init__(f"{reason} at input byte {offset}, output byte {produced}")
        self.offset = offset
        self.produced = produced
        self.reason = reason


def strings(source, limit):
    """Yield compressed and expanded offsets, kind, count, and operand bytes."""
    offset = produced = 0
    while offset < len(source):
        control = source[offset]
        kind, count = control >> 6, control & 63
        if kind == 1 or not count:
            raise SCBError(offset, produced, "reserved control" if kind == 1 else "zero count")
        end = offset + 1 + (count if kind == 0 else int(kind == 3))
        if end > len(source):
            raise SCBError(offset, produced, "truncated operand")
        if produced + count > limit:
            raise SCBError(offset, produced, "output overrun")
        yield offset, produced, kind, count, source[offset + 1:end]
        offset = end
        produced += count
    if produced != limit:
        raise SCBError(offset, produced, "short output")


def decode(source, *, prime, expected=BLOCK_SIZE):
    """Decode a bare SCB string, with no terminator or trailing padding."""
    prime_byte = bytes([prime])
    out = bytearray()
    for _, _, kind, count, operand in strings(source, expected):
        out.extend(operand if kind == 0 else (prime_byte if kind == 2 else operand) * count)
    return bytes(out)


def tape_files(rows):
    """Yield file bodies from three-mark groups, recording suspect label indexes."""
    if not rows or rows[-1][1] != END:
        raise ValueError("explicit EOD required")
    marks = [-1] + [i for i, (_, marker, _) in enumerate(rows) if marker == 0]
    if (len(marks) - 1) % 3 or marks[-1] != len(rows) - 2:
        raise ValueError("unexpected three-mark layout")
    for start, data, trailer, end in zip(marks[::3], marks[1::3], marks[2::3], marks[3::3]):
        indexes = [*range(start + 1, data), *range(trailer + 1, end)]
        labels = [(i, label(rows[i][2])) for i in indexes]
        header = next((entry for i, entry in labels if i < data and entry
                       and entry["type"] == "HDR1"), None)
        tail = next((entry for i, entry in labels if i > trailer and entry
                     and entry["type"] in ("EOF1", "EOV1")), None)
        issues = [i for i, entry in labels if entry is None or rows[i][1] & ERR]
        yield header, tail, issues, range(data + 1, trailer)


def audit(path):
    before = digest(path)
    rows = list(frames(path))
    files = []
    for header, tail, issues, body in tape_files(rows):
        counts = Counter()
        exceptions = []
        for logical, index in enumerate(body, 1):
            offset, marker, payload = rows[index]
            flagged = bool(marker & ERR)
            try:
                for _ in strings(payload, BLOCK_SIZE):
                    pass
                kind = "scb"
            except SCBError as error:
                kind = "raw_size" if len(payload) == BLOCK_SIZE else "unclassified"
                if kind == "unclassified":
                    exceptions.append(dict(record=logical, frame=index, tap_offset=offset,
                                           length=len(payload), flagged=flagged,
                                           input_offset=error.offset, produced=error.produced,
                                           reason=error.reason))
            counts[f"{kind}_{'flagged' if flagged else 'clean'}"] += 1
        files.append(dict(file=header["identifier"] if header else None,
                          file_sequence=header["file_sequence"] if header else None,
                          declared=tail["block_count"] if tail else None,
                          suspect_or_unrecognized_labels=issues,
                          observed=len(body), counts=dict(counts), unclassified=exceptions))
    if digest(path) != before:
        raise ValueError("input changed during audit")
    volume = label(rows[0][2])
    return dict(sha256=before, volume=volume["volume"] if volume and
                volume["type"] == "VOL1" else None, files=files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tape")
    args = parser.parse_args()
    print(json.dumps(audit(args.tape), indent=2))


if __name__ == "__main__":
    main()
