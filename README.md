# QIC Tape Recovery

A reproducible, evidence-preserving workflow for reading aging QIC magnetic tapes and reconstructing their logical contents, developed during recovery of early IBM AS/400 SAVSYS and licensed-program cartridges.

**Start here:** [Technical recovery process](docs/RECOVERY_PROCESS.md) — hardware, SCSI drive configuration, raw record capture, error behavior, capture journals, intra-tape and cross-tape reconstruction, validation, and case studies.

## What this project is

The aim is to preserve **what the drive actually returned**, including incomplete and questionable reads, then construct separately identified recovery candidates supported by the original capture evidence. We do not silently replace damaged data with zeros or claim that a complete-looking tape image is a verified restore.

The principal tested setup uses a Tandberg TDC 4100, Linux generic SCSI, a 32 KiB variable-length READ(6) request, and per-read metadata. Earlier Linux tape-device, fixed-block, and `tapecopy` experiments informed this approach.

## Current status

The detailed process is documented, and the tested **TDC 4100 direct-SG capture script** is available at [scripts/tape2tap-sg.py](scripts/tape2tap-sg.py). Archive inventories, reconstruction manifests, synthetic test fixtures, and repeatable validation tools remain planned additions. **No original IBM tape images, customer data, or sensitive archive contents are included here.**

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

_Last documentation update: November 22, 2026._
