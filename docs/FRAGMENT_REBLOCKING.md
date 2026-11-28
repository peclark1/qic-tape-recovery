# Fragment-boundary recovery

The offline toolkit now includes a separate `scripts/reblock.py` command. It preserves bytes, not necessarily historical accuracy. Use only on a closed, IBM-labelled SIMH TAP derivative with an explicit end marker and intact matching HDR1/EOF1 or EOV1 labels. Run capture validation and retain physical journals first.

```sh
python3 scripts/reblock.py audit source.tap > fixed-plan.json
python3 scripts/reblock.py reblock source.tap fixed.tap fixed-manifest.json
python3 scripts/reblock.py audit source.tap --allow-variable > experimental-plan.json
python3 scripts/reblock.py reblock source.tap experimental.tap experimental-manifest.json --allow-variable
```

The default looks for a run of adjacent error-flagged, 512-byte-aligned partial reads shorter than 24,576 bytes, followed by an unflagged short suffix. Only groups totaling 24,576 bytes are selected. Fixed-only plans can leave unresolved excess blocks. The explicit variable mode also permits other lengths up to 32,760 bytes, but refuses a file unless the proposed reduction exactly reconciles its IBM trailer count. Both modes refuse excess proposals. Inspect each audit before producing an image; exact counts constrain but do not prove boundaries. Parameters can be changed with `--block-size` and `--quantum` for independently established media profiles.

A full-sized good record after a suspect prefix is not automatically appended: prior captures demonstrated 512-byte overlaps. The tool does not delete overlapping data, fill gaps, repair byte values, merge across tape marks, or remove error flags. It recognizes the observed IBM header/data/trailer layout, not arbitrary labelled tapes. It is intentionally not a generalized solver or a journal decoder. Nonaligned suspect reads and full-size suspect blocks are left intact.

Output paths must be new. The derivative and separate boundary manifest include source and output SHA-256, zero-based source record indexes (including labels/marks, excluding EOD), source/output frame offsets, constituent lengths, marker words and payload hashes, classification and before/after counts. A second parse checks file payload hashes, counts, all labels, filemarks and EOD. The source is not modified. This boundary manifest is distinct from the existing donor-substitution schema.

## Case-study evidence (November 2026)

On one early OS/400 distribution volume, a fixed 24,576-byte installation file had 11 physical frames although its IBM trailer declared nine. Three adjacent fragments of 9,216, 8,192 and 7,168 bytes totaled exactly 24,576; joining them preserved all data and uncertainty. Across the volume, fixed-length joins accounted for 41 excess boundaries (including the IML file), and the variable-length heuristic accounted for 30 more. All eight declared file counts could be reconciled in an experimental derivative. Variable-length discrepancies between acquisition passes remain unresolved. Earlier SAVSYS captures independently confirmed the split-read phenomenon with complete good-status reads on other passes, but also demonstrated overlaps and agreeing suspect reads that later proved wrong.

Neither structural reconciliation nor successful emulator IPL demonstrates complete restoration. No original IBM payload, tape image, or customer data is published here. Synthetic fixtures exercise fixed and variable joins, flags, padding, count gating, overlap refusal and immutable inputs.
