#!/usr/bin/env python3
"""Offline tools for the project's SG capture dialect. Python 3.11+, standard library."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from collections import Counter

END = 0xffffffff
ERR = 0x80000000

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def require(ok, message):
    if not ok:
        raise ValueError(message)

def frames(path):
    """Yield (offset, marker, payload); reject unsupported markers and trailing bytes."""
    with Path(path).open("rb") as f:
        while True:
            offset = f.tell()
            raw = f.read(4)
            if not raw:
                return
            require(len(raw) == 4, f"truncated marker at {offset}")
            m, = struct.unpack("<I", raw)
            if m in (0, END):
                yield offset, m, b""
                if m == END:
                    require(not f.read(1), "bytes after EOD")
                    return
                continue
            n = m & ~ERR
            require(0 < n <= 32768, f"unsupported record length at {offset}")
            data = f.read(n)
            require(len(data) == n, f"truncated payload at {offset}")
            if n % 2:
                require(f.read(1) == b"\0", f"invalid padding at {offset}")
            require(f.read(4) == raw, f"trailer mismatch at {offset}")
            yield offset, m, data

def validate(directory):
    d = Path(directory)
    image = d / "capture.tap"
    expected = (d / "SHA256SUMS").read_text().split()
    require(len(expected) == 2 and expected[1] == "capture.tap"
            and expected[0] == digest(image), "capture.tap checksum mismatch")
    entries = iter(frames(image))
    pos = reads = 0
    file = None
    counts = Counter()
    sidecars = set()
    ended = stopped = False
    for line in (d / "capture.jsonl").read_text().splitlines():
        e = json.loads(line)
        kind = e["event"]
        counts[kind] += 1
        require(not ended and not stopped, "journal event after stop")
        if kind == "start":
            require(file is None and reads == 0, "duplicate start")
            file = e["file"]
            require(e["buffer"] == 32768 and file >= 0, "unsupported capture profile")
            continue
        require(file is not None, "missing start")
        if kind == "read_retries":
            require(reads == 0 and 1 <= e["current"] <= 24, "invalid retry event")
            continue
        if kind in ("error", "interrupted"):
            stopped = True
            continue
        reads += 1
        require(e["read"] == reads and e["file"] == file and e["offset"] == pos,
                f"journal position mismatch at read {reads}")
        n = e["bytes"]
        require(isinstance(n, int) and 0 <= n <= 32768, "invalid byte count")
        if kind in ("record", "suspect_record", "filemark", "end_of_data"):
            item = next(entries, None)
            require(item is not None, "journal references absent TAP entry")
            off, m, data = item
            wanted = {"record": n, "suspect_record": n | ERR,
                      "filemark": 0, "end_of_data": END}[kind]
            require(off == pos and m == wanted and len(data) == n,
                    f"TAP/journal mismatch at read {reads}")
            pos += 4 if m in (0, END) else 8 + n + n % 2
            if kind == "filemark":
                file += 1
            if kind == "end_of_data":
                ended = True
        elif kind in ("possible_gap", "transport_or_residual_error", "unexpected_result"):
            require(kind != "possible_gap" or n == 0, "nonempty possible gap")
            stopped = kind != "possible_gap"
        else:
            raise ValueError(f"unknown event {kind}")
        if kind == "record":
            require(n > 0 and not any(e[k] for k in ("status", "host", "driver")),
                    "invalid good record status")
        if kind != "record" and n:
            name = f"read-{reads:09d}.bin"
            require(e.get("payload_file") == name, "invalid sidecar name")
            payload = (d / name).read_bytes()
            require(len(payload) == n, "sidecar length mismatch")
            if kind == "suspect_record":
                require(payload == data, "sidecar/TAP mismatch")
            sidecars.add(name)
        else:
            require("payload_file" not in e, "unexpected sidecar")
    require(file is not None, "missing start")
    require(next(entries, None) is None, "unjournaled TAP entry")
    require(sidecars == {p.name for p in d.glob("read-*.bin")}, "unreferenced sidecar")
    return {"image_sha256": expected[0], "journal_sha256": digest(d / "capture.jsonl"),
            "counts": dict(counts), "reads": reads, "observed_eod": ended,
            "warning": "Structural integrity only; gaps and suspect data may remain."}

def label(data):
    if len(data) != 80:
        return None
    for encoding in ("cp037", "ascii"):
        try:
            s = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if s[:4] in ("VOL1", "HDR1", "HDR2", "EOF1", "EOF2", "EOV1", "EOV2"):
            out = {"type": s[:4], "encoding": encoding, "text": s}
            if s[:4] == "VOL1":
                out["volume"] = s[4:10].strip()
            if s[:4] in ("HDR1", "EOF1", "EOV1"):
                out.update(identifier=s[4:21].strip(), file_set=s[21:27].strip(),
                           volume_sequence=s[27:31], file_sequence=s[31:35],
                           block_count=int(s[54:60]) if s[54:60].isdigit() else None)
            return out
    return None

def inventory(path):
    """Map observed TAP records; do not infer original boundaries after damage."""
    volume = None
    files = []
    current = None
    phase = None
    for offset, m, data in frames(path):
        if m == END:
            break
        if m == 0:
            if phase == "header":
                phase = "data"
            elif phase == "data":
                phase = "trailer"
            continue
        l = label(data) if not m & ERR else None
        if l and l["type"] == "VOL1":
            volume = l["volume"]
        elif l and l["type"] == "HDR1":
            current = {"volume": volume, "header": l, "header_offset": offset,
                       "records": [], "trailer": None}
            files.append(current)
            phase = "header"
        elif current and phase == "trailer" and l and l["type"] in ("EOF1", "EOV1"):
            current["trailer"] = l
        elif current and phase == "data":
            current["records"].append({"offset": offset, "length": len(data),
                                       "sha256": sha(data), "suspect": bool(m & ERR)})
    for f in files:
        t = f["trailer"]
        f["observed_count"] = len(f["records"])
        f["count_matches"] = bool(t and t["block_count"] == len(f["records"]))
        f["identity_matches"] = bool(t and all(t[k] == f["header"][k] for k in
                                  ("identifier", "file_set", "volume_sequence", "file_sequence")))
    return files

def key(f):
    h = f["header"]
    return (f["volume"], h["identifier"], h["file_set"], h["volume_sequence"], h["file_sequence"])

def candidates(a, b, same_tape=False):
    """Only propose same-size records in unique, identical two-sided anchor intervals.
    No ordinal matching across unanchored gaps; no automatic cross-tape repair."""
    left, right = inventory(a), inventory(b)
    out = []
    for f in left:
        if same_tape:
            matches = [g for g in right if key(f) == key(g)]
        else:
            matches = [g for g in right if f["header"]["identifier"] == g["header"]["identifier"]
                       and f["header"]["volume_sequence"] == g["header"]["volume_sequence"]
                       and f["header"]["file_sequence"] == g["header"]["file_sequence"]]
        if len(matches) != 1 or sum(key(h) == key(f) for h in left) != 1:
            continue
        g = matches[0]
        x, y = f["records"], g["records"]
        cx = Counter(v["sha256"] for v in x if not v["suspect"])
        cy = Counter(v["sha256"] for v in y if not v["suspect"])
        lookup = {v["sha256"]: j for j, v in enumerate(y) if not v["suspect"]}
        anchors = [(i, lookup[v["sha256"]]) for i, v in enumerate(x)
                   if not v["suspect"] and cx[v["sha256"]] == cy[v["sha256"]] == 1]
        # Reject rearranged anchors rather than choosing an arbitrary alignment.
        if any(q[1] <= p[1] for p, q in zip(anchors, anchors[1:])):
            continue
        for (i,j), (k,l) in zip(anchors, anchors[1:]):
            if k-i != l-j:
                continue
            for u,v in zip(x[i+1:k], y[j+1:l]):
                if u["length"] != v["length"]:
                    continue
                out.append({"file": list(key(f)), "target": u, "source": v,
                            "anchors": [x[i]["sha256"], x[k]["sha256"]],
                            "classification": ("agreement" if u["sha256"] == v["sha256"]
                                else "candidate" if u["suspect"] and not v["suspect"]
                                else "conflict")})
    return out

def reconstruct(base, donor, output, manifest, same_tape):
    require(same_tape, "cross-tape substitution is not automated")
    paths = [Path(p).resolve() for p in (base, donor, output, manifest)]
    require(len(set(paths)) == 4 and not paths[2].exists() and not paths[3].exists(),
            "inputs/outputs must be distinct; outputs must be new")
    # Require complete, matching labeled stream counts before simple replacement.
    for p in paths[:2]:
        files = inventory(p)
        require(files and all(f["count_matches"] and f["identity_matches"] for f in files),
                "logical counts/labels unresolved; use manual fragment reconciliation")
        require(list(frames(p))[-1][1] == END, "input lacks EOD")
    proposals = candidates(base, donor, True)
    replacements = {p["target"]["offset"]: p for p in proposals
                    if p["classification"] == "candidate"}
    source = {o: d for o, m, d in frames(donor) if m not in (0, END) and not m & ERR}
    changes = []
    with paths[2].open("xb") as out:
        for offset, marker, data in frames(base):
            if offset in replacements:
                p = replacements[offset]
                data = source[p["source"]["offset"]]
                require(sha(data) == p["source"]["sha256"], "donor changed")
                # Preserve error flag until independent review, even with good donor.
                changes.append(p)
            word = struct.pack("<I", marker)
            out.write(word)
            if marker not in (0, END):
                out.write(data + (b"\0" if len(data) % 2 else b"") + word)
    report = {"schema_version": 1, "relationship": "operator-asserted same physical tape",
              "base_sha256": digest(base), "donor_sha256": digest(donor),
              "output_sha256": digest(output), "changes": changes,
              "remaining_error_flags": sum(bool(m & ERR) for _, m, _ in frames(output)
                                           if m != END),
              "limitations": "Same-length anchored candidates only; flags retained; no gap repair."}
    with paths[3].open("x") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate").add_argument("directory")
    sub.add_parser("inventory").add_argument("image")
    for name in ("compare", "reconstruct"):
        q = sub.add_parser(name)
        q.add_argument("base")
        q.add_argument("donor")
        q.add_argument("--same-tape", action="store_true")
        if name == "reconstruct":
            q.add_argument("output")
            q.add_argument("manifest")
    a = p.parse_args()
    try:
        if a.command == "validate":
            result = validate(a.directory)
        elif a.command == "inventory":
            result = inventory(a.image)
        elif a.command == "compare":
            result = {"base_sha256": digest(a.base), "donor_sha256": digest(a.donor),
                      "relationship": "same tape (asserted)" if a.same_tape else "different recordings",
                      "comparisons": candidates(a.base, a.donor, a.same_tape)}
        else:
            result = reconstruct(a.base, a.donor, a.output, a.manifest, a.same_tape)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as e:
        p.exit(1, f"ERROR: {e}\n")

if __name__ == "__main__":
    main()
