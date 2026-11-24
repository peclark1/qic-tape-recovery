# Software dependencies and provenance

The project uses standalone utilities from Hercules, Linux tape/SCSI tools, project-specific Python software and separate validation environments. Not all tools are required for every stage. Hercules emulation itself is not required for physical tape acquisition.

## Hercules tapecopy

The original workflow used Ubuntu's packaged Hercules 3.13 (`sudo apt install hercules`) to obtain `tapecopy`. Earlier archives produced by a collaborator used this utility with a Linux SCSI tape device and AWS output. Typical commands (verify the actual device first):

```sh
sudo tapecopy /dev/nst0 capture.aws
# Conversion, not physical acquisition:
vtapecp capture.aws capture.tap
```

`tapecopy` also supports writing an AWS image to a physical tape; this is a destructive operation on the destination and must never be performed on an original archival cartridge.

### Modified Hyperion build

Upstream: https://github.com/SDL-Hercules-390/hyperion

Historical build identifier: `4.9.1.11612-SDL-gee86c4de` (abbreviated source revision `ee86c4de`; confirm full revision before reproducing). The stock `MAX_TAPE_BLKSIZE` was 2,097,152 bytes. Requests of 2 MiB and 64 KiB failed on the tested TDC 4100 setup; 32 KiB worked. This is a host read request limit observed in that setup, not a universal QIC record length.

The local modification to `tapecopy.c` was:

```diff
-static BYTE buf[ MAX_TAPE_BLKSIZE ];
+static BYTE buf[ 32768 ];
```

Historical edit command:

```sh
sed -i 's/static BYTE buf\[ MAX_TAPE_BLKSIZE \];/static BYTE buf[ 32768 ];/' tapecopy.c
```

Inspect the resulting diff and rebuild against the matching upstream revision. The portable build depended on `libhercs.so` and `libhercu.so` as well as normal system libraries. Historical launch example (adjust installation path):

```sh
sudo env LD_LIBRARY_PATH="$HOME/tapecopy-portable/lib" \
  "$HOME/tapecopy-portable/bin/tapecopy" /dev/nst0 capture.aws
```

Use a fresh output path. Record the executable hash, linked libraries, full source revision, build configuration and patch. Exact historical build flags and binary hashes remain to be recovered. The modified utility informed development of the direct SG_IO reader; it is not required by that Python script and does not replace its error journals and suspect-payload preservation.

## AWS/TAP conversion

Jay Maynard's `vtapecp` was used in the earlier archival workflow to convert AWS masters to TAP. Retain the original AWS file and hash both source and converted output. Validate record lengths and filemarks independently. Exact source URL, version and license of the historical executable remain to be verified; do not substitute an unrelated similarly named program. Earlier `copytape` experiments are historical, not a recommended acquisition method: host reads could aggregate 512-byte records and the old reader could stop at two consecutive tape marks.

## Linux and project utilities

| Tool | Role | Dependency status |
|---|---|---|
| Python 3 | Direct SG_IO acquisition and offline analysis | Required for project reader |
| mt-st (`mt`) | Rewind and configure block mode before SG capture | Acquisition workflow |
| sg3-utils (`sg_inq`, etc.) | SCSI identification and diagnostics | Acquisition/diagnostics |
| lsscsi | Match generic and sequential device nodes | Recommended |
| jq | JSONL inspection and read-only monitoring | Optional |
| coreutils (`sha256sum`, etc.) | Hash verification and artifact inspection | Recommended |
| Git | Source revision and documentation tracking | Development |
| ddrescue, pipx | Present in historical host inventory | Not established as required by tape reader |

On Ubuntu, a starting environment is `sudo apt install python3 mt-st sg3-utils lsscsi jq git`. This does not install the modified Hyperion utility or vtapecp. Record OS/kernel, package versions, SCSI controller/driver and drive firmware for each capture. See [recovery procedure](RECOVERY_PROCESS.md) and [project reader](../scripts/tape2tap-sg.py).

## Functional validation (separate from acquisition)

- Solstice: https://github.com/neutronstarz/solstice — AS/400 emulation and install/restore experiments. Record exact source revision, configuration and tested tape hashes.
- ZuluSCSI firmware: https://github.com/ZuluSCSI/ZuluSCSI-firmware — tape-image presentation to physical AS/400 hardware. Record hardware model, firmware revision and device configuration.

Neither is a dependency of the direct-SCSI capture script.

## Distribution and reproducibility

This document references external projects rather than vendoring binaries or source. Verify upstream licenses at the exact revision before redistributing modified source or binaries, and retain applicable notices and source obligations. The QIC recovery repository has not yet selected its own software license. Publish a minimal patch and reproducible build instructions separately once the original revision/build configuration has been confirmed. Never distribute proprietary tape payloads as test fixtures.
