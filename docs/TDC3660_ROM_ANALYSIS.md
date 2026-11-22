# Tandberg TDC 3660 ROM: first-pass reverse engineering

21 November 2026. Source: `tdc3660-rom.BIN`, 65,536 bytes, SHA-256
`94db7bead17538a87b6f1b300b3111cb6ff0ec280cd4ad0de8a1453582b44fae`.

This is a **static analysis of this exact ROM image**. The opcode table, branch
targets, and literal bytes below were verified against the image. Hardware
register assignments, tape-format routines, and differences from IBM firmware
remain to be established with an IBM ROM and/or live bus traces. Addresses are
68HC11 addresses and equal offsets in this full-size image.

## Identification and memory layout

* The processor is a Motorola **68HC11-family** device. Examples: `8E 05 FE`
  at `$5052` loads the stack pointer with `$05FE`; `18 CE 04 06` at `$674D`
  loads Y with `$0406`; `3B` returns from an interrupt. The reset vector at
  `$FFFE` points to `$5051`. The exact chip variant cannot be established from
  the ROM alone. See the [Motorola M68HC11 Reference Manual](https://bitsavers.trailing-edge.com/components/motorola/68HC11/1991_M68HC11RM_Reference_Manual_Rev3.pdf).
* `$0000–$4FFF` is `FF` fill. Code/data begins at `$5000`; the reset entry is
  `$5051`. The last populated nonvector region ends at `$ECA4`. Interrupt
  vectors occupy `$FFD6–$FFFF`; the region preceding them is largely `FF`.
  Gaps of `FF` also appear inside the code region. This is a 64 KiB *address
  space dump*, not 64 KiB of contiguous executable instructions.
* `$5000`: `(C) TANDBERG DATA 1987SCSI`; `$501A`: a 51-byte standard INQUIRY
  response with peripheral type `01` (sequential access), removable `80`,
  version `02`, response format `02`, and additional length `2E`. Vendor is
  `TANDBERG`, product is ` TDC 3600       `, four-byte revision field is
  `=08:`, and subsequent vendor bytes begin `15CREATED011593`. The combined
  visible string is `=08:15CREATED011593`; the date-shaped suffix probably
  means 15 January 1993, but that interpretation is not proven. Handler
  `$6BA4` explicitly sends this buffer via `$83C1`. The generic family name
  does not identify the physical drive's exact 3620/3640/3660 variant.

## SCSI target path

`$663F` loops over SCSI activity. It fetches a CDB into RAM beginning at
`$0406`, handles pending state and media checks, and calls `$674D`. The latter
chooses the six-byte table at `$6787` for commands with high opcode bits zero
or the ten-byte table at `$6828` otherwise. It compares the opcode, checks
reserved bits of the remaining CDB bytes against per-command masks, loads a
two-byte handler address, and returns it in X. `$6736` executes `JSR 0,X`.
An unrecognized opcode or disallowed CDB bit takes the error path at `$677E`.
The command tables terminate at sentinel bytes `$6827` and `$6858` (`80`).

Each six-byte entry has `opcode | five disallowed-bit masks | handler address`
(8 bytes); each ten-byte entry has `opcode | nine masks | handler address`
(12 bytes). A mask bit of one must be zero in the submitted CDB. The masks do
not, by themselves, prove that every combination of allowed bits succeeds.

| Opcode | Command | ROM handler | Opcode | Command | ROM handler |
|---|---|---:|---|---|---:|
| `00` | Test Unit Ready | `762A` | `01` | Rewind | `744D` |
| `03` | Request Sense | `7405` | `05` | Read Block Limits | `7335` |
| `08` | Read | `72F6` | `0A` | Write | `76AD` |
| `10` | Write Filemarks | `76FE` | `11` | Space | `7525` |
| `12` | Inquiry | `6BA4` | `13` | Verify | `763E` |
| `14` | Recover Buffered Data | `73C1` | `15` | Mode Select | `6D21` |
| `16` | Reserve Unit | `742A` | `17` | Release Unit | `73DA` |
| `18` | Copy | `6B24` | `19` | Erase | `6B74` |
| `1A` | Mode Sense | `70CB` | `1B` | Load/Unload | `6BCF` |
| `1D` | Send Diagnostic | `7473` | `1E` | Prevent/Allow Removal | `72A9` |
| `2B` | Locate | `6C5B` | `34` | Read Position | `7344` |
| `3B` | Write Buffer | `7687` | `3C` | Read Buffer | `72BA` |

The labels follow the SCSI operation codes and relevant handler behavior.
In particular, `$7687` uses the inbound data-transfer helper `$817F`, whereas
`$72BA` uses the outbound helper `$81DE`. A scanned older Tandberg manual
appears to reverse the `3B`/`3C` names in its command list; the ROM follows
the usual SCSI names. This ROM's table also differs from that older list
(for example, `02` is absent, and it adds `2B`/`34`). Treat the table in the
image as authoritative for this revision.

## Tape and mode details recovered

* **Fixed block size:** `$7335` returns six literal bytes from `$733E`:
  `00 00 02 00 02 00`. In READ BLOCK LIMITS format, both maximum and minimum
  are `$0200` = **512 bytes**. Tandberg's 3600 reference manual explicitly
  states the same for QIC-11, QIC-24, QIC-120, and QIC-150. This claim applies
  to this ROM/drive family, not to the user's other Tandberg models.
* **Mode Sense:** `$70CB` builds output at RAM `$038E`; `$7151` generates a
  four-byte header and `$7183` an eight-byte block descriptor. At `$71B1`,
  `LDD #$0200` puts the 512-byte block length in descriptor bytes 6–7.
  `$7296` finds mode pages using 10-byte records at `$65D4`:
  page `02` (16 bytes), `10` (16), `11` (8), vendor page `20` (12), and `3F`
  (all supported pages, aggregate 52). Generators begin at `$71D0`, `$71E5`,
  `$720F`, `$7233`, and `$7261` respectively. More work is needed to
  interpret every field and the MODE SELECT validation rules.
* **Density mapping:** `$7183` consults the two-byte table at `$6610` for the
  density byte it reports. Its mapping from internal value to SCSI density
  code is `01→04`, `04→05`, `06→0F`, `07→10`, `03→84`, `05→82`,
  `02→05`, and fallback `00→00`. Tandberg's manual identifies `04` as
  QIC-11 4-track, `05` as QIC-24, `0F` as QIC-120, `10` as QIC-150,
  and `84` as a vendor code for QIC-11 9-track. The meaning of `82` and
  each internal selector still needs tracing.
* **Sense path:** `$7405` runs `$690B` to assemble a fixed-format sense
  buffer at `$035C` (up to `$32` = 50 bytes). `$690B` searches the four-byte
  lookup records at `$6A18–$6B1F`, which appear to map drive/internal error
  values to returned sense fields. The individual record meanings have not
  yet been validated; do not treat the raw record bytes as direct SCSI sense
  keys.
* **Media/state handling:** `$6680–$6731` has explicit cases for INQUIRY
  (`12`), PREVENT/ALLOW (`1E`), READ BUFFER (`3C`), WRITE BUFFER (`3B`),
  TEST UNIT READY (`00`), and REQUEST SENSE (`03`) before generic dispatch.
  Read (`72F6`) and write (`76AD`) reach distinct mechanical/data paths.

## Relevance to the IBM B10 drive

This ROM establishes a Tandberg baseline: it advertises the generic TDC 3600
identity, accepts the listed SCSI commands, and advertises fixed 512-byte
blocks. It **cannot establish what IBM changed**. An IBM ROM dump from the
actual B10 drive would allow a byte-level comparison, relocation-aware
function matching, and focused inspection of INQUIRY, MODE SENSE/SELECT,
REQUEST SENSE, SCSI vendor commands, and drive parameters. Even if the PCB
is similar, do not assume the EPROMs are interchangeable without identifying
the controller, ROM map, checksums, and mechanical calibration values.

The next strongest evidence without an IBM ROM is a read-only SCSI capture of
the B10 drive's INQUIRY, READ BLOCK LIMITS, MODE SENSE (including page `3F`),
and REQUEST SENSE responses alongside this drive's responses. The ROM
comparison would then distinguish generic firmware differences from IBM
specific protocol or identity changes.

## Sources and reproducibility

* Primary evidence: the supplied `tdc3660-rom.BIN` at the addresses listed.
* [Tandberg Data, *TDC 3620/3640/3660 Reference Manual*](https://bitsavers.org/pdf/tandbergData/TDC_3620_3640_3660_Reference_Manual.pdf), especially software interface section 9 and READ BLOCK LIMITS section 9.3.9. It is a reference for the family; its command list appears to describe an earlier firmware revision.
* [Motorola, *M68HC11 Reference Manual*](https://bitsavers.trailing-edge.com/components/motorola/68HC11/1991_M68HC11RM_Reference_Manual_Rev3.pdf), instruction set and reset vectors.
* [T10, SCSI-2 working draft catalog](https://www.t10.org/drafts.htm), for historical command naming and format context.
* Companion `tdc3660_disasm.py` provides a **partial**, conservative
  68HC11 listing helper. For example, `python3 tdc3660_disasm.py 674D 6787`.
  It emits unknown opcodes as bytes and is not a full recursive disassembler;
  do not linearly disassemble the command/data tables and call them code.