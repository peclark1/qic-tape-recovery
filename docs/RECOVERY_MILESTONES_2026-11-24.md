# Recovery milestones and remaining work — November 24, 2026

This dated supplement updates the [technical recovery process](RECOVERY_PROCESS.md). Earlier acquisition statistics remain historical observations, not superseded measurements. Original tape payloads and private inventories are not published.

## 1988 SAVSYS: functional OS/400 V1R1 recovery

On November 22–23, the recovered 1988 two-volume SAVSYS set, together with B10 MULIC material, enabled installation of OS/400 V1R1 in the Solstice B10 environment. The system reached the OS/400 Main Menu and ran WRKSYSSTS. Manual B-mode IPL was the working path; repeated normal A-mode attempts stalled at C6004036 while successful sequential disk IPCF reads continued. The cause of the A-mode behavior remains unresolved.

This demonstrates a successful installation and interactive operation with the selected recovery material. It does not establish byte-exact recovery of either tape, a successful unattended A-mode IPL, or restoration of every saved object. The exact input tape derivative hashes, emulator revision, configuration and test logs should be associated with the functional result before independent reproduction is claimed. Do not retroactively mark earlier derivatives as restore-tested.

## 1989 SAVSYS volume 2

The D01 structural review accounted for 47 IBM save streams and 4,174 logical 24,576-byte data blocks, of which 4,162 were entirely supported by good-status reads (99.7125% of blocks). Twelve blocks retained 116,736 suspect-status bytes. Structural verification is not proof of byte-perfect recovery.

A subsequent experimental D02 used eight sector-level substitutions totaling 3,274 bytes, retained 12 error flags and left 13 discrepancies unresolved. Sector-level comparison and replacement byte counts are different metrics; the error flags must not be cleared merely because a donor was available. Preserve D01 and D02 independently, including input/output hashes and a per-replacement manifest.

Targeted FSF/LOCATE attempts were reported unable to position beyond damaged regions. Offline reconstruction was therefore preferred over repeating unsuccessful positioning attempts. The previously identified reread targets remain useful as an evidence ledger, not an instruction to immediately transport the tape again:

| Logical file | Candidate indices (as recorded in the recovery report; verify indexing convention before use) |
|---|---|
| A01 | 1, 2, 7, 10 (reference positions 1052, 1053, 1058, 1061) |
| QCBL | 58 |
| QDCT | 6 |
| QHLPSYS | 410, 424, 429 |
| QOFC | 173 |
| QPDA | 318 |
| QSSP | 360 |

Nine mismatching 512-byte sectors in A01 were prioritized in the earlier report. Reconcile this list with D02's actual manifest before selecting new targets.

Proposed functional checks on a disposable system: list labels with `DSPTAP DEV(TAP01) DATA(*LABELS) OUTPUT(*PRINT)`, then inspect save/restore metadata with `DATA(*SAVRST)`. Test PPSIUTIL (sequence 28), then PPSIPROD (25), PPSIPROTO (26), PPSITEST (27), verifying sequence and library identity against the actual listing before issuing restore commands. Record the exact derivative and logs; these checks are proposed, not reported as completed here.

## Mechanical damage and transport decisions

Observed problems include degraded tension/brake bands, localized oxide loss, damage near reel ends, and tape tangling. Heads were reported to remain clean, with no observed progressive deterioration during the relevant reads. These observations are specific to the examined cartridges, not a diagnosis applicable to all QIC media. Baking is not part of the current recovery procedure.

Document photographs and interventions before transport, including rebanding and any visible damage location. Keep physical observations separate from inferred logical block positions. Map damaged regions using observed read order, labels and stable anchors; a read ordinal is not a physical distance along the tape. Stop if shedding, abnormal transport, or further damage is observed. Prefer offline reconciliation where additional passes offer little new evidence.

The TDC 3660 fixed-512-byte comparison remains a candidate for separate acquisition research, not a proven replacement for the TDC 4100 variable-record workflow. See [firmware analysis](TDC3660_ROM_ANALYSIS.md).

## Working recovery queue

| Material | Next evidence needed |
|---|---|
| 1988 SAVSYS V1/V2 | Bind successful V1R1 installation to exact derivative hashes and logs; retain remaining unresolved block ledger. |
| 1989 SAVSYS V2 | Reconcile D02 manifest and discrepancies; validate on disposable system; compare matched 1988 evidence where justified. |
| 1994 SAVSYS V1/V2 | Preserve unobserved volume transition and A01 donor/conflict map; do not claim missing target bytes as recovered. |
| COBOL/400 R02M00 | Reconcile probe, continuation and tail batches in actual acquisition order; establish gaps and IBM trailer counts before claiming complete reconstruction. |
| V1R2 SS1 volumes 1–3 | Confirm acquisition inventory before planning further transport; no new capture result asserted here. |

## Reproducibility priorities

1. Publish a synthetic-data TAP/JSONL validator and IBM label parser.
2. Define a manifest that records source capture SHA-256, read ordinal, source byte range, target logical position, evidence classification, conflicts and derivative SHA-256.
3. Publish alignment and reconstruction utilities with tests for split records, zero-byte errors, ambiguous alignment and cross-recording conflicts.
4. Maintain separate private object inventories and public metadata-only summaries.
5. Record functional test results against exact image hashes, hardware/emulator versions and IPL mode.

A functional installation and a historically exact archive are complementary goals; neither substitutes for the other.
