# QIC Tape Recovery

A reproducible, evidence-preserving workflow for reading aging QIC magnetic tapes and reconstructing their logical contents, developed during recovery of early IBM AS/400 SAVSYS and licensed-program cartridges.

**Start here:** [Technical recovery process](docs/RECOVERY_PROCESS.md) — hardware, SCSI drive configuration, raw record capture, error behavior, capture journals, intra-tape and cross-tape reconstruction, validation, and case studies.

**Second-drive comparison:** The guide now documents the Tandberg TDC 3660 / TDC 3600-family fixed-512-byte tests and includes [the corresponding firmware analysis](docs/TDC3660_ROM_ANALYSIS.md).

**Latest recovery milestone:** [November 24 recovery update](docs/RECOVERY_MILESTONES_2026-11-24.md) — successful OS/400 V1R1 installation in Solstice, 1989 SAVSYS reconstruction status, mechanical damage observations, and the remaining recovery queue.

**Software dependencies:** [Third-party utilities and provenance](docs/SOFTWARE_DEPENDENCIES.md) — Hercules tapecopy, the 32 KiB modification, AWS/TAP conversion, Linux tools and validation environments.

## Why conventional tape dumping was insufficient

Conventional tape imaging works well when the drive returns intact records and filemarks through the operating system's sequential tape interface (such as Linux `/dev/nst0`). The difficulty encountered in this recovery effort was not simply an inability to read a tape: **a failed read could return recoverable bytes, advance the tape, and leave the next read inside an original recorded block.** The ordinary stream interface and conventional copying workflow did not preserve enough evidence to reconstruct those damaged regions reliably.

| Observed failure mode | Consequence for conventional acquisition | Evidence-preserving approach |
|---|---|---|
| Medium error with partial payload | A stream read can report an I/O error without exposing the bytes the drive actually recovered. | Direct Linux SG_IO captures returned bytes, SCSI status, sense and residual; questionable bytes are retained and flagged. |
| Read error followed by a successful short read | A successful read may be a fragment of the same original block, not the next complete record. Counting reads as original blocks can misalign subsequent data. | Preserve actual returned lengths and use IBM labels, expected block sizes and independent acquisition passes to establish logical boundaries. |
| Zero-byte medium error | The number of missing original bytes or records may be unknown; skipping or zero-filling can conceal that uncertainty. | Journal a possible gap without inventing data; stop after bounded unsuccessful attempts. |
| Failed or uncertain tape repositioning | Skipping to a later file can lose recoverable material or leave the next capture's starting position ambiguous. | Preserve every observed filemark and read event; verify position using actual labels and known-good anchors. |
| Different results on repeated passes | A single apparently complete dump may retain errors or omit fragments that another pass recovers. | Keep independent captures immutable and compare them offline, with explicit provenance for any reconstructed derivative. |

A concrete example from the COBOL/400 recovery was a medium-error read containing **7,168 suspect bytes**, followed by a good-status read containing **13,736 bytes**. Both were preserved by direct SCSI acquisition. Their relationship to the original recorded block required separate logical reconstruction; neither the failed status nor the subsequent good status was sufficient to establish the original record boundary.

The earlier stream-based recovery attempts repeatedly stopped near file 25 of that cartridge. Direct SCSI acquisition preserved partial payloads and allowed further controlled reads and continuation captures. The Hercules 32 KiB modification described below addressed a separate problem: the size of the read request accepted by the TDC 4100. It did not, by itself, solve the damaged-record evidence problem.

**The central lesson is to separate acquisition from reconstruction.** Capture what the drive actually returns, including errors and uncertainty, before attempting to rebuild the original logical tape. A tape image that reaches end-of-data is not necessarily complete, historically accurate, or restorable.

See [the technical recovery process](docs/RECOVERY_PROCESS.md) for the exact SCSI commands, observed error patterns, retry behavior and reconstruction case studies. These findings describe the tested hardware and software path; other drives and acquisition utilities may expose errors differently.

## Important: Hercules `tapecopy` modification for the TDC 4100

**Stock Hercules `tapecopy` did not work with the tested TDC 4100 at its default 2 MiB read size.** A 64 KiB request also failed; a 32 KiB (32,768-byte) request succeeded. To reproduce the earlier physical-tape acquisition workflow, modify `tapecopy.c` in [SDL Hercules Hyperion](https://github.com/SDL-Hercules-390/hyperion) (historical build `4.9.1.11612-SDL-gee86c4de`):

```diff
-static BYTE buf[ MAX_TAPE_BLKSIZE ];
+static BYTE buf[ 32768 ];
```

Rebuild `tapecopy` after applying this change. This is a verified workaround for this TDC 4100 setup, not a universal QIC block size. The project’s newer direct-SG Python reader already uses a 32 KiB request and does **not** require Hercules or this patch. See [software dependencies and provenance](docs/SOFTWARE_DEPENDENCIES.md) for the historical build, shared libraries, conversion utilities and remaining reproducibility details.

## What this project is

This repository preserves the methods, experiments, software modifications, and lessons learned during a specific tape recovery effort so that others working with aging magnetic media can evaluate, reproduce, or adapt them where useful. The procedures are documented as observed, including unsuccessful approaches and unresolved limitations; they are not a universal prescription for tape recovery.

The aim is to preserve **what the drive actually returned**, including incomplete and questionable reads, then construct separately identified recovery candidates supported by the original capture evidence. We do not silently replace damaged data with zeros or claim that a complete-looking tape image is a verified restore.

The principal tested setup uses a Tandberg TDC 4100, Linux generic SCSI, a 32 KiB variable-length READ(6) request, and per-read metadata. Earlier Linux tape-device, fixed-block, and `tapecopy` experiments informed this approach.

## Offline recovery toolkit

[Usage and limitations](docs/RECOVERY_TOOLKIT.md) — Python 3.11+ capture validation, IBM label inventory, anchored same-tape/cross-tape comparison, conservative derivative reconstruction, a versioned manifest schema and synthetic regression tests. A separate [fragment boundary audit and reblocking tool](docs/FRAGMENT_REBLOCKING.md) supports conservative fixed-size joins and opt-in experimental variable-length joins. Gap recovery remains research work.

## Current status

The detailed process is documented, and the tested **TDC 4100 direct-SG capture script** is available at [scripts/tape2tap-sg.py](scripts/tape2tap-sg.py). Initial offline validation, inventory, comparison, reconstruction manifests and synthetic tests are now available; conservative fragment reblocking is now available; gap recovery and broader archive-specific validation remain planned. **No original IBM tape images, customer data, or sensitive archive contents are included here.**

Please distinguish preservation milestones:

1. An image file exists.
2. Its framing, checksum, journal, and error sidecars validate.
3. The IBM logical tape structure validates.
4. All relevant logical blocks are recovered or remaining uncertainty is explicitly mapped.
5. An emulator or physical AS/400 demonstrates the intended restore/install behavior.

Those are different levels of evidence. An observed tape end does not imply levels 3–5.

## Contributing and reuse

This repository documents experiments as well as successful recovery methods. Record exact hardware and firmware, drive settings, script revision, original image hashes, error logs, derived-image hashes, and unresolved ambiguities with each reported result. Avoid publishing original proprietary tape contents.

The project does not yet declare a software license; discuss intended licensing before importing or redistributing third-party code.

_Last documentation update: November 27, 2026._
