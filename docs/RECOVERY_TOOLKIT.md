# Offline recovery toolkit (initial release)

Requires Python 3.11 or newer; no third-party Python packages or tape hardware are needed. The acquisition script is unchanged.

Run from the repository root:

```sh
python3 scripts/recovery_toolkit.py validate /path/to/capture-directory
python3 scripts/recovery_toolkit.py inventory /path/to/capture.tap > inventory.json
python3 scripts/recovery_toolkit.py compare pass1.tap pass2.tap --same-tape > comparison.json
python3 scripts/recovery_toolkit.py compare 1988.tap 1994.tap > cross-tape.json
python3 scripts/recovery_toolkit.py reconstruct pass1.tap pass2.tap derivative.tap manifest.json --same-tape
python3 -m unittest discover -s tests -v
```

Use fresh output paths. Validate both source capture directories first. Do not run against actively growing captures. The same-tape switch is an explicit operator assertion about physical cartridge identity, not a fact the software can prove.

| Command | Scope |
|---|---|
| validate | Checks capture TAP checksum, framing, journal positions, read ordinals, file numbers and suspect sidecar correspondence. Reports witnessed EOD separately. Does not independently decode all SCSI sense semantics or certify original completeness. |
| inventory | Decodes 80-byte ASCII/EBCDIC labels and lists observed data frames, offsets, lengths, hashes, flags and trailer count/identity checks. Observed frames are not necessarily original logical blocks. |
| compare | Reports equal-length interior records between unique, ordered, matching good anchors; reports conflicts and candidate replacements. Cross-recording comparisons are read-only; absent rows mean no supported comparison, not agreement. |
| reconstruct | Creates a separate same-tape derivative with a versioned manifest. Requires matching observed/declared counts and label identities and EOD on both inputs. Replaces only equal-length flagged records with anchored good donor candidates; retains error flags for review. |

The original donor-replacement command intentionally does not join fragments, resolve zero-byte gaps, infer volume joins, insert cross-tape donor bytes, or establish byte-exact restoration. In particular, some of the historical captures from this effort will require manual reconciliation before this simple reconstruction path can be used. A matching count does not prove the original block boundaries. The inventory is a basic parser for the observed label layout, not a complete OS/400 save-stream decoder.

The [manifest schema](../schemas/reconstruction-manifest-v1.json) records source and output image hashes, target and donor TAP offsets, lengths and payload hashes, file identity, anchor hashes and remaining error flags. Offsets point to TAP leading markers. Original capture journals are the source of read ordinals and gap evidence; retain them with the source images. The v1 manifest does not yet embed all journal evidence or per-byte fragment provenance. Keep a separate unresolved-gap ledger and independently verify any derivative. No claim of historical fidelity follows from the manifest alone.

Synthetic tests generate entirely invented EBCDIC labels and payloads in temporary directories; no original IBM data is included. Tests cover odd record padding, invalid trailers, label counts, suspect sidecars, a zero-byte gap, same-tape replacement, conflicting good reads, unequal-length candidates and rejection of cross-tape writes. GitHub Actions runs the suite on pushes and pull requests.

## Fragment boundary recovery

See [fragment reblocking](FRAGMENT_REBLOCKING.md) for the new separate audit/reblock command, confidence policy, manifest and limitations.

## Next extensions

- Extend the fragment tool with journal-backed fragment spans and independently verified original block lengths.
- Report unmatched intervals explicitly, including leading/trailing gaps and reordered anchors.
- Add per-read and per-byte provenance, multiple donors, and independently validated cross-tape substitution proposals.
- Expand label/volume validation using synthetic multi-volume fixtures, and validate manifests in CI.
- Evaluate against archived captures privately before recommending production use.
