#!/usr/bin/env python3
"""Conservative IBM-labelled SIMH fragment-boundary reconstruction."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from recovery_toolkit import END, ERR, frames, label, require, sha, digest

LIMIT = 32760

def sections(rows):
    """Recognize the observed three-mark IBM label/data/trailer layout."""
    require(rows and rows[-1][1] == END, "explicit EOD required")
    groups, group = [], []
    for i, (_, m, _) in enumerate(rows[:-1]):
        if m == 0:
            groups.append(group)
            group = []
        else:
            group.append(i)
    require(not group and groups and len(groups) % 3 == 0,
            "unsupported label/filemark layout")
    out = []
    for k in range(0, len(groups), 3):
        hdr, body, tail = groups[k:k+3]
        def labels(indices):
            result = []
            for i in indices:
                require(not rows[i][1] & ERR, "suspect label")
                l = label(rows[i][2])
                require(l is not None, "unrecognized label")
                result.append(l)
            return result
        h, t = labels(hdr), labels(tail)
        types = [l["type"] for l in h]
        require(types in (["HDR1"], ["HDR1", "HDR2"],
                          ["VOL1", "HDR1"], ["VOL1", "HDR1", "HDR2"]),
                "unsupported header labels")
        require(k == 0 or "VOL1" not in types, "unexpected VOL1")
        require([l["type"] for l in t] in
                (["EOF1"], ["EOF1", "EOF2"], ["EOV1"], ["EOV1", "EOV2"]),
                "unsupported trailer labels")
        header = next(l for l in h if l["type"] == "HDR1")
        trailer = t[0]
        require(all(header[x] == trailer[x] for x in
                    ("identifier", "file_set", "volume_sequence", "file_sequence")),
                "header/trailer identity mismatch")
        require(trailer["type"] != "EOV1" or k == len(groups)-3,
                "EOV before last file")
        count = trailer["block_count"]
        require(count is not None and 0 <= count <= len(body),
                "invalid declared count or missing blocks")
        out.append((header["identifier"], body, count))
    return out

def payload_digest(rows, indices):
    h = hashlib.sha256()
    for i in indices:
        h.update(rows[i][2])
    return h.hexdigest()

def plan(rows, block_size=24576, quantum=512, allow_variable=False):
    require(0 < quantum < block_size <= LIMIT and block_size % quantum == 0,
            "invalid block size/fragment quantum")
    report = []
    for name, body, declared in sections(rows):
        excess = len(body) - declared
        groups = []
        i = 0
        while excess and i < len(body):
            def prefix(pos):
                _, marker, data = rows[body[pos]]
                return bool(marker & ERR) and 0 < len(data) < block_size and len(data) % quantum == 0
            if not prefix(i):
                i += 1
                continue
            j = i
            while j < len(body) and prefix(j):
                j += 1
            if j == len(body):
                break
            _, marker, suffix = rows[body[j]]
            indices = body[i:j+1]
            total = sum(len(rows[n][2]) for n in indices)
            # Never append a complete good block to a suspect prefix: possible overlap.
            if not marker & ERR and 0 < len(suffix) < block_size and total <= LIMIT:
                kind = "fixed-size" if total == block_size else "variable-inferred"
                if kind == "fixed-size" or allow_variable:
                    groups.append({
                        "kind": kind, "source_records": indices,
                        "source_offsets": [rows[n][0] for n in indices],
                        "source_lengths": [len(rows[n][2]) for n in indices],
                        "source_markers": [rows[n][1] for n in indices],
                        "source_payload_sha256": [sha(rows[n][2]) for n in indices],
                        "merged_length": total,
                        "merged_sha256": payload_digest(rows, indices),
                    })
            i = j+1 if not marker & ERR else j
        reduction = sum(len(g["source_records"])-1 for g in groups)
        require(reduction <= excess, f"{name}: candidates exceed declared excess")
        if allow_variable:
            require(reduction == excess, f"{name}: variable plan does not reconcile count")
        report.append({"file": name, "declared": declared, "observed": len(body),
                       "projected": len(body)-reduction, "remaining_excess": excess-reduction,
                       "payload_sha256": payload_digest(rows, body), "groups": groups})
    return report

def audit(source, block_size=24576, quantum=512, allow_variable=False):
    before = digest(source)
    rows = list(frames(source))
    report = plan(rows, block_size, quantum, allow_variable)
    require(digest(source) == before, "source changed during read")
    return {"schema_version": 1, "operation": "boundary-only-reblock",
            "source_sha256": before, "block_size": block_size, "fragment_quantum": quantum,
            "allow_variable": allow_variable, "files": report,
            "limitations": "Heuristic boundaries, not byte recovery; no overlap/gap repair; flags retained."}

def reblock(source, output, manifest, block_size=24576, quantum=512, allow_variable=False):
    paths = [Path(p).resolve() for p in (source, output, manifest)]
    require(len(set(paths)) == 3 and not paths[1].exists() and not paths[2].exists(),
            "distinct new output paths required")
    before = digest(paths[0])
    rows = list(frames(paths[0]))
    report = plan(rows, block_size, quantum, allow_variable)
    require(digest(paths[0]) == before, "source changed during read")
    merges = {g["source_records"][0]: g for f in report for g in f["groups"]}
    made = []
    try:
        with paths[1].open("xb") as out:
            made.append(paths[1])
            i = 0
            while i < len(rows):
                _, marker, data = rows[i]
                g = merges.get(i)
                if g:
                    idx = g["source_records"]
                    require(idx == list(range(i, idx[-1]+1)), "nonadjacent fragments")
                    data = b"".join(rows[n][2] for n in idx)
                    marker = len(data) | ERR
                    g["output_offset"] = out.tell()
                    i = idx[-1]+1
                else:
                    i += 1
                word = struct.pack("<I", marker)
                out.write(word)
                if marker not in (0, END):
                    out.write(data + b"\0"*(len(data)%2) + word)
        rebuilt = list(frames(paths[1]))
        original_sections, new_sections = sections(rows), sections(rebuilt)
        require(len(original_sections) == len(new_sections) == len(report), "file count changed")
        for (name, old, count), (newname, new, newcount), f in zip(original_sections, new_sections, report):
            require(name == newname and count == newcount and len(new) == f["projected"]
                    and payload_digest(rows, old) == payload_digest(rebuilt, new),
                    "output payload or label count changed")
        def nondatastream(items, secs):
            data = {i for _, body, _ in secs for i in body}
            return [(m, d) for i, (_, m, d) in enumerate(items) if i not in data]
        require(nondatastream(rows, original_sections) == nondatastream(rebuilt, new_sections),
                "labels or marks changed")
        require(digest(paths[0]) == before, "source changed")
        result = {"schema_version": 1, "operation": "boundary-only-reblock",
                  "source_sha256": before, "output_sha256": digest(paths[1]),
                  "block_size": block_size, "fragment_quantum": quantum,
                  "allow_variable": allow_variable, "files": report,
                  "payload_verified": True,
                  "remaining_error_flags": sum(bool(m & ERR) for _, m, _ in rebuilt if m != END),
                  "limitations": "Heuristic boundaries, not byte recovery; no overlap/gap repair; flags retained."}
        with paths[2].open("x") as f:
            made.append(paths[2])
            json.dump(result, f, indent=2)
            f.write("\n")
        return result
    except Exception:
        for p in made:
            p.unlink()
        raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("audit", "reblock"):
        q = sub.add_parser(name)
        q.add_argument("source")
        if name == "reblock":
            q.add_argument("output")
            q.add_argument("manifest")
        q.add_argument("--block-size", type=int, default=24576)
        q.add_argument("--quantum", type=int, default=512)
        q.add_argument("--allow-variable", action="store_true")
    a = p.parse_args()
    try:
        args = (a.block_size, a.quantum, a.allow_variable)
        result = (audit(a.source, *args) if a.command == "audit"
                  else reblock(a.source, a.output, a.manifest, *args))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as e:
        p.exit(1, f"ERROR: {e}\n")

if __name__ == "__main__":
    main()
