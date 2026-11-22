# Recovering aging QIC tapes: acquisition, errors, and reconstruction

**Project:** IBM AS/400 QIC tape preservation  
**Working methodology:** November 19–22, 2026  
**Status:** Evidence-based field report and reproducible procedure; ongoing recovery research  
**Audience:** people imaging cartridge tapes, interpreting SCSI sense, reconstructing IBM-labeled files, and independently validating archival claims.

> **Scope and honesty:** This guide records the actual TDC 4100 experiments and the recovery work through November 22. It is not a specification for every QIC drive or every AS/400 tape. Figures are identified as *observed*, *derived*, or *still unresolved*. The original archives and detailed journals are retained separately; their data is not distributed by this public repository.

## 1. What we are trying to preserve

A tape archive has several different layers, which must not be confused:

1. **Physical medium:** original cartridge, tape condition, density/format and drive behavior.
2. **SCSI acquisition evidence:** each command, returned status, sense bytes, residual, transferred bytes, and the exact order of observations.
3. **Tape-image framing:** ordered variable-length records, filemarks, end marker and flags for questionable reads.
4. **IBM logical tape structure:** ANSI/IBM labels, file identifiers, sequence numbers, block counts, volume continuations and OS/400 save-file structure.
5. **Reconstructed information:** logical records repaired from independent reads of the *same* tape and, where justified, corroborating copies on *other* tapes.
6. **Usability:** a tape image can be parsed and perhaps mounted but must still be tested by the intended software or hardware.

**An image ending in an end-of-data marker is not, by itself, a complete or accurate backup.** A drive can return the end marker while earlier records remain corrupt, truncated or missing.

Our preservation rule is to keep the raw acquisition artifacts **immutable**. Every repair produces a separate derivative, accompanied by a manifest recording its inputs, the exact bytes selected and the remaining uncertainty.

### Workflow at a glance

~~~text
Photograph/inventory cartridge and inspect physical condition
  -> Identify drive, controller, firmware, block behavior
  -> Configure read mode and verified session retry setting
  -> Capture from known position; journal EVERY SCSI read
  -> Preserve original TAP + suspect .bin + JSONL + SHA-256
  -> Validate TAP framing, offsets, events and checksums
  -> Parse IBM labels, volumes, filemarks and block counts
  -> Align independent passes of the SAME physical tape
  -> Reassemble split records and select supported replacements
  -> Compare corresponding data on OTHER tapes/versions
  -> Record conflicts, gaps, source provenance and confidence
  -> Build separately identified derivative; revalidate
  -> Test read/restore/install on emulator or physical AS/400
~~~

## 2. Hardware and why we chose this approach

The primary working reader was a **Tandberg TDC 4100**, firmware **0801**, attached by SCSI to an Ubuntu Linux acquisition host. The host presented the same transport as the Linux non-rewinding sequential tape device **/dev/nst0** and generic SCSI device **/dev/sg1** during these sessions. Earlier AS/400 work also involved an IBM-labeled Tandberg TDC 3600 and a TDC 3660; do **not** assume their SCSI behavior matches the 4100.

The archive setup used a legacy Adaptec SCSI host adapter in our Ubuntu work (AHA-2940AU in the earlier setup); record the exact controller and driver for each new installation rather than assuming these device paths are permanent.

Before mounting a fragile cartridge, inspect its condition and replace a degraded tension band when necessary. Record all interventions (including rebanding), along with photographs, label discrepancies, and whether the write-protect mechanism was engaged. Do not perform unnecessary repeat transports on a visibly deteriorating tape.

### Identify the drive and match both Linux device nodes

~~~bash
sudo apt install mt-st sg3-utils jq
lsscsi -g                        # if lsscsi is installed
cat /proc/scsi/scsi
sudo sg_inq /dev/sg1             # verify vendor/product/firmware
sudo mt -f /dev/nst0 status
~~~

**Do not trust /dev/sg1 or /dev/nst0 without checking.** SCSI enumeration can change after a reboot or another device being added. The two nodes must refer to the *same physical drive*. Only one reader should control a drive at a time.

### Why 32 KiB, and not a very large buffer?

An independent comparison using **tapecopy** was particularly informative:

- Stock tapecopy used a roughly **2 MiB** tape READ request and immediately failed with **EINVAL**.
- A **64 KiB** request also failed.
- A **32 KiB (32,768 byte)** request worked.
- A tapecopy build modified to use 32 KiB could read the original variable-record structure, including early MULIC data, and we were able to write/read a replacement tape for comparison.

The meaningful constraint was the **requested maximum transfer size**, not evidence that every original tape record is exactly 32 KiB. Actual record sizes vary: IBM labels are typically **80 bytes**, while payload records can be much larger. A smaller read buffer can also interact with device behavior at damaged records. We therefore record the **returned length** of every read and independently reconstruct original IBM block boundaries.

The **TDC 3660** behaved differently in later testing: its 32 KiB variable READ was rejected (ILLEGAL REQUEST, ASC/ASCQ 24/00), while fixed 512-byte handling worked. Therefore these instructions are a documented **TDC 4100 profile**, not a universal compatibility setting.

## 3. Preparing the TDC 4100 for the current capture workflow

Our earlier tools operated through the standard **/dev/nst0** stream interface and used file-spacing recovery. That approach is useful for healthy tapes but loses useful information when a drive returns CHECK CONDITION with partial payload, because a normal read often surfaces only an I/O error.

The later tool uses Linux **SG_IO** on **/dev/sg1** and explicitly receives status, sense and residual. It records suspect payloads rather than simply throwing them away.

### Reset position and enable variable blocks

~~~bash
sudo mt -f /dev/nst0 rewind
sudo mt -f /dev/nst0 setblk 0
sudo mt -f /dev/nst0 status
~~~

The **setblk 0** request selects variable-block mode through the Linux tape driver. Do this *before* beginning direct-SG acquisition. Once a direct-SG capture starts, avoid other commands to the same drive: the Linux tape driver's cached file/block position is **not updated by SG_IO reads**.

### Control the internal read retry count

The version of **tape2tap-sg.py** used in the November 20–22 runs supports:

~~~text
--read-retries 1
~~~

When supplied, the tool verifies that the target is a **TANDBERG TDC 4100**, reads SCSI **MODE SENSE(6) error-recovery page 0x01**, checks whether its read-retry field is changeable, then issues **MODE SELECT(6)** *only if necessary* and reads the page back to verify the requested count.

The tool accepts **1–24** retries, and records the previous and requested values. A session transcript included **Drive read retries: 5 -> 1**; a separate attempt at **0** was rejected, with **5** still present on readback.

**One retry is not necessarily universally optimal.** It is a useful comparison setting because the drive spends less time internally attempting the same damaged region and can expose fragments for further analysis. Higher retry counts may instead yield additional corrected data on a different pass. Keep the retry setting in the archive metadata and compare outcomes empirically. Internal retries are the *drive's* behavior and are not the same as commanding another pass from the host.

The more conservative historical direct-SG reader did **not** send MODE SELECT at all. Keep these versions distinct: the later script intentionally supports the TDC 4100-specific retry setting; it is not a general-purpose mode-page editor.

### Capture from the start of the tape

A representative command from our actual runs:

~~~bash
output="$HOME/tape-archives/SAVSYS-102388-1-of-2-sg-pass3-1retry"

if [ -e "$output" ]; then
    echo "ERROR: Archive directory already exists: $output"
else
    if sudo mt -f /dev/nst0 rewind &&
       sudo mt -f /dev/nst0 setblk 0; then
        sudo python3 -u "$HOME/tape2tap-sg.py" \
            "$output" --device /dev/sg1 --read-retries 1
        printf 'Capture exit status: %s\n' "$?"
    fi
fi
~~~

The program creates a fresh directory, then writes:

| File | Meaning |
|---|---|
| **capture.tap** | Ordered TAP-framed data and tape markers; suspect payloads carry an error flag. |
| **capture.jsonl** | One machine-readable event per READ, including good reads, errors, filemarks, end and settings. |
| **read-#########.bin** | Exact bytes returned with a non-good result when payload was supplied; retained independently of the TAP representation. |
| **SHA256SUMS** | SHA-256 checksum of capture.tap. |

The current script **starts from the drive's current position**, it does **not** rewind on its own. The wrapper above establishes the starting position. The **--start-file** parameter merely labels the first observed file number; it **does not move the tape**.

A separate capture directory is required for every pass: do not overwrite an earlier pass. Capture console output as well when possible. The script supports the explicit end-of-data state, but whether the material already read is logically complete remains a separate question.

### Monitor without modifying the capture

~~~bash
tail -f "$output/capture.jsonl"

# Simple event totals in another terminal:
jq -s '{
  reads: (map(select(.read != null)) | length),
  good: (map(select(.event == "record")) | length),
  suspect: (map(select(.event == "suspect_record")) | length),
  possible_gaps: (map(select(.event == "possible_gap")) | length),
  filemarks: (map(select(.event == "filemark")) | length)
}' "$output/capture.jsonl"

jq -r 'select(.event == "suspect_record" or
              .event == "possible_gap") |
       [.file, .read, .bytes, .residual, .sense] | @tsv' \
    "$output/capture.jsonl"
~~~

The monitor is read-only. A previous monitoring command failed because it applied **split()** to an already-parsed jq array; that was a monitor bug, **not** a failed capture. Parse JSON as JSON instead of assuming string input.

## 4. Exactly what one SCSI read does

The current reader sends a six-byte **READ(6)** command equivalent to:

~~~text
08 02 00 80 00 00
~~~

Here **0x8000 = 32,768** is the requested length, and the variable-record/SILI semantics of the command are intentional for this drive. The generic SCSI call uses a 32,768-byte data buffer and records both **SG_IO residual** and **SCSI status**.

A journal event contains at least:

~~~json
{
  "read": 1234,
  "file": 4,
  "offset": 28765432,
  "bytes": 7168,
  "status": 2,
  "host": 0,
  "driver": 8,
  "residual": 25600,
  "sense": "..."
}
~~~

These numbers illustrate the fields; this is **not a verbatim archived event**. The code classifies results from the actual returned status/sense bytes and payload. The journal records the TAP offset **before** the event is written, so the data and context can be correlated later.

### Observed categories

| Event | Drive/host evidence | What the capture does |
|---|---|---|
| **record** | GOOD status and nonempty payload | Write one TAP data entry, advance good read count. |
| **suspect_record** | CHECK CONDITION / MEDIUM ERROR and nonempty returned bytes | Save bytes in TAP as an error-flagged entry **and** in a read-#########.bin sidecar. |
| **possible_gap** | MEDIUM ERROR with **zero** returned bytes | Log an unquantified possible loss; no fabricated zero-filled data entry. |
| **filemark** | For this drive, fixed-format sense indicates filemark, with ASC/ASCQ 00/01 and empty payload | Write TAP filemark, increment observed file index. |
| **end_of_data** | For this drive, BLANK CHECK with ASC/ASCQ 00/05 and empty payload | Write TAP end marker and finish. |
| **unexpected_result / transport_or_residual_error** | Other status, impossible residual, or a transport fault | Stop rather than pretending unknown data is valid. |

The drive's **sense key 0x03** is a medium error. The **0x08** key identifies blank check for the observed end condition. These details describe the verified TDC 4100 behavior and must be revalidated for other devices.

The current capture permits a bounded continuation after nonempty medium-error returns. It stops after **three consecutive zero-byte medium-error reads**, rather than risk endlessly reading unproductive regions. An error can also terminate a run without observed EOD. Such a capture is **partial**.

### What happens physically at a bad region?

The SCSI drive firmware is responsible for its own error-correction and recovery attempts. Depending on its retry setting, it may perform repeated tape-motion/read attempts before returning a status. We observed delays and repeated activity around difficult locations; **we did not instrument the transport motor or prove the number/direction of every physical motion**.

More importantly, a failed READ can **advance the drive**. The next READ may return another piece of what was originally a single tape record. We have seen patterns resembling:

~~~text
original recorded block
     [--- A ---------- B ---------- C ---]

one pass:
  CHECK CONDITION / MEDIUM ERROR -> suspect bytes A
  GOOD status                    -> shorter bytes B
  subsequent READ                -> next material C
~~~

This illustration is conceptual. We have not automatically proved that any neighboring A/B/C fragments share the same original record. Doing so requires independent alignment evidence from labels, expected block sizes, matching sequences and/or other passes.

**The central trap:** a GOOD status after an error can be a **cleanly delivered fragment**, not proof of a whole original record. Equating *one successful SG read* to *one original IBM tape data block* can shift every later record index and make an otherwise plausible recovery wrong.

For example, a direct COBOL diagnostic read preserved **7,168 suspect bytes**, followed by a **13,736-byte good-status read**. Both were important evidence; their relationship to the intended logical block needed reconstruction rather than simple concatenation.

## 5. Encoding the acquired tape

The current image is a **SIMH-style TAP** stream. Its ordinary record is:

~~~text
4-byte little-endian record length
record payload (actual bytes returned)
optional single zero pad byte if payload length is odd
matching 4-byte little-endian record length
~~~

For **suspect_record** entries, the tool ORs **0x80000000** into the length word (front and back) to mark questionable data. A typical parser should calculate the actual payload length after removing that flag; it must also preserve/report the flag and verify both length words. Do not blindly treat the high bit as payload length.

Special 32-bit little-endian markers include:

- **0x00000000** — tape filemark.
- **0xFFFFFFFF** — end-of-data marker in the saved image.

A TAP filemark is **not** an IBM EOF1 label, and an image end marker is **not** itself evidence of a physical, verified end-of-volume. Do not infer a filemark from a zero-length read without the corresponding tape-status evidence.

**SIMH, E11 and AWS conventions are not interchangeable by name.** We independently tested variable-record framing and encountered odd-length padding differences between SIMH and E11 handling. The correct image format must be selected explicitly when mounting in an emulator or ZuluSCSI; a framing mismatch can make a valid record appear to have a huge/incorrect trailer length. Conversion is a derived operation; preserve and hash the source image.

Some tools do not understand the flagged-length convention or suspect records; only use them on a derivative after checking their interpretation. A structurally parseable TAP does not mean every embedded IBM block is good.

## 6. Preserve and independently validate each acquisition

On completion, keep **all** of:

- unmodified capture.tap and its SHA256SUMS;
- capture.jsonl with SCSI status/sense, byte counts, offsets, file numbers and start/retry/end events;
- every suspect sidecar even if a different pass later supplies clean bytes;
- console transcript, hardware/controller configuration, capture source-script version/hash;
- photos and interventions on the physical tape;
- tape identity and aliases, including conflicting external and internal labels.

Verify these independently:

1. TAP record-header and trailer lengths match, allowing for the high-bit error flag and odd padding.
2. Every TAP byte range matches the corresponding journal offset/length.
3. Every suspect sidecar is identical to its TAP payload.
4. Filemark/end events agree with the TAP markers and acquisition stop condition.
5. Checksums of every artifact and ZIP bundle agree with the archive manifest.
6. Image parsing never silently drops a suspect entry or invents placeholder bytes.

For the November 19 review, “**verified bundle**” meant ZIP CRC, saved TAP SHA-256, TAP framing/offset consistency and sidecar equality had passed. This establishes **file and provenance integrity**, **not** recovery of the original tape data or restore success.

The capture script's SHA256SUMS covers capture.tap. A full preservation bundle should separately hash the journal, sidecars, metadata and any derived images. Use unique identifiers such as **SAV88-02** for acquisitions and **SAV88-V1-D02** for derivatives instead of relying only on directory names.

## 7. Recovering a tape from its own multiple passes

The reconstruction starts **after** raw acquisition, on copies of the preserved artifacts.

### Step A — build a physical-read event table

Read each JSONL in sequence. Record:

- acquisition ID and source cartridge ID;
- read number, observed tape file, event kind, payload byte count and TAP offset;
- status, sense key/ASC/ASCQ, residual and sidecar path;
- hash of the bytes (where nonempty);
- filemark boundaries and unknown-position warnings.

A read count is **not yet** a logical record count. Preserve zero-byte errors and pass-specific record fragmentation.

### Step B — parse IBM tape labels and map the logical files

AS/400 save tapes in our set use 80-byte EBCDIC labels. Relevant record identifiers include **VOL1**, **HDR1**, **HDR2**, **EOF1**, **EOF2**, **EOV1** and **EOV2**. Decode only appropriate 80-byte label records (our initial inspection used EBCDIC **CP037**) and retain the undecoded original bytes.

Build an IBM-level map containing:

- volume serial, volume sequence and creation date;
- file identifier and IBM file sequence;
- beginning and ending label/filemark boundaries;
- declared block counts from closing labels;
- whether a file continues onto another volume.

Examples from the 1988 set include **QFILEIML**, **QFILEMCD**, **QSYS**, and **QSS1.L2924.A01**. On our SAVSYS volumes, the low-level structure contains **multiple tape filemarks around one logical IBM file**. For example, 1988 volume 2 showed **46 IBM files and 138 filemarks**; do not treat those as 138 different IBM save files.

Use **trailer-declared block counts** to detect missing or extra logical records. An exact count is a useful structural constraint but cannot itself prove the recovered bytes are correct.

### Step C — align at stable anchors, not raw read indices

Align different passes using a combination of:

- matching VOL1/HDR/EOF/EOV labels, file IDs and sequence numbers;
- good-status payload SHA-256 equality;
- unique adjacent records and expected logical block size;
- declared block numbers/counts and filemark patterns;
- evidence on both sides of a suspect region.

Read indices can diverge when a damaged original block produces multiple SG reads or one pass stops prematurely. Where alignment is ambiguous, **record an unknown interval** instead of arbitrarily shifting all subsequent data.

### Step D — reconstruct split logical records

At a suspected split, enumerate candidate ordered fragments and lengths. A concatenation is acceptable only if the proposed original-record length and surrounding alignment match the IBM logical layout and there is no conflicting evidence. Prefer a complete, independently read good-status copy over a fragment reassembly.

Classify each original logical record conservatively:

| Class | Evidence |
|---|---|
| **direct good** | A complete, correctly aligned original record was obtained with good status. |
| **corroborated reconstructed** | Two independent passes supply identical reassembled bytes for the same original block. |
| **single-pass reconstructed / suspect** | Candidate bytes can be aligned but lack independent confirmation or contain medium-error evidence. |
| **conflict** | Competing plausible reads/reconstructions differ in one or more bytes. |
| **missing / unknown** | Record existence/position is indicated but actual bytes or extent are not defensibly recovered. |

Record the exact source read numbers, fragment offsets, selected byte ranges, expected length and hash for **every repaired original block**.

### Step E — construct an immutable-manifest derivative

Use a source image as a base only after proving logical alignment. Emit an independent TAP derivative whose blocks are ordered by **IBM original logical record**, not by arbitrary post-error SG call boundaries. Preserve filemark structure, labels and termination markers only where justified by evidence.

Include a machine-readable manifest with every replacement: output file/block/byte range, source capture/read/offset, source hashes, evidence class, and any unresolved discrepancy. Retain an error flag on a candidate that remains suspect. Re-parse the derivative and re-check declared block counts.

**Never claim that a block is recovered simply because we constructed the expected number of bytes.**

### Concrete example: 1988 SAVSYS volume 1

A documented intermediate derivative (**SAV88-V1-D01**) used the second acquisition as its base and applied **eight cross-pass replacements** from the first. It preserved **24 filemarks**, EOV1 and EOD, but still had **194 fragment-level error flags**.

The next derivative (**SAV88-V1-D02**) reconciled fragments to **5,420 IBM-declared logical data blocks**:

| Recovery classification in D02 | Logical blocks |
|---|---:|
| Complete good-status read | 5,298 |
| Identical reconstruction from two passes | 21 |
| Conflict between passes | 3 |
| One-pass suspect evidence | 98 |
| **Total accounted for** | **5,420** |

Thus **122 logical blocks remained flagged** in D02 (21 + 3 + 98), even though the original block sequence and all 5,420 logical positions had been accounted for. The 21 agreeing reconstructions were evidence-supported but still tracked as reconstructed/error-derived, not silently rebranded as pristine.

A **third read pass** of 1988 volume 1 later reached the observed end-of-data with **5,451 good-status reads, 159 suspect reads and 24 filemarks**. Cross-pass analysis reduced the previously unresolved population from **122 to 90** logical records; **32 acquired clean support** (QFILEIML 1, QFILEMCD 8, QSYS 9, A01 14). Good-status **read count** and IBM logical **block count** are not interchangeable: the former can include pieces of a damaged original block.

These are **dated stages**, not contradictory final success counts. A later D04-style merged candidate and subsequent analysis must retain its own input hashes, algorithm and residual-error ledger. We have not claimed a fully error-free 1988 SAVSYS based solely on the pass-3 totals.

### Concrete example: 1988 SAVSYS volume 2

The 1988 volume-2 acquisition returned **4,237 good-status reads, 22 medium-error returns, and 138 filemarks**. The IBM-level check identified **46 labeled logical files** with matching EOF1 trailer block counts.

A separate **SAV88-V2-D01** candidate rejoined **21 split original records** using the observed fragments, preserved all **138 filemarks** and the end-of-data marker, and **left 22 uncertain records identified as uncertain**. No original payload bytes were changed merely to force the expected sizes. This illustrates why reconstructing the record boundaries and resolving their bytes are two separate tasks: the TAP structure can be repaired while specific payloads still require more evidence.

## 8. Comparing independent physical tapes

A second, physically different cartridge may contain the *same file identifier* or much of the same logical data. This can be a powerful source of independent corroboration, but is not a license to transplant every byte.

### Two distinct kinds of comparison

**Same tape, multiple passes:** same intended recording, so byte-for-byte equality of aligned original logical blocks is strong evidence; differences identify acquisition uncertainty or fragment boundaries.

**Different tape, possibly different date/release:** the same IBM filename can hold substantially similar material but may contain legitimate different content, metadata or patches. Comparison must identify which spans are **stable and identical**, which genuinely differ, and whether donor bytes could represent the target's original content at all.

Our SAVSYS collections are particularly useful for this:

- **1988 SAVSYS**, two volumes, internally dated **88297**, first volume sequence 0001.
- **1989 SAVSYS**, two volumes, used to compare repeated data and volume continuations.
- **1994 SAVSYS**, two volumes, internally dated **94250**, first volume sequence 0001.
- **QSS1.L2924.A01** appears across these sets and continues between volumes; that continuation is a key alignment opportunity.

The October 1988 set also includes an external-label discrepancy on volume 2 (**102888** versus internally dated **88297**). Physical labels and IBM internal metadata should both be preserved, rather than silently “correcting” either.

### Cross-tape procedure

1. First reconstruct each tape's **own** most defensible logical block map.
2. Match IBM **file identifier + volume/file sequence + relative block location**, not only a string match.
3. Select long, independently **good** anchor ranges. Require consistency on both sides of the proposed replacement interval.
4. Compare full bytes and hashes, not just EBCDIC text or apparent semantics.
5. Identify release-specific changes and per-volume metadata before accepting any borrowed block.
6. When one target region is unreadable, label a donor block as **borrowed from a different recording**; never call it an original read of the target.
7. If two independent donors agree in a region where the target is absent, preserve that as stronger corroboration, but still state that target identity is inferred.
8. Store all conflicts, lengths, offsets, donor versions and hashes in a manifest; recompute validation after insertion.

### Cross-tape corroboration outside A01

The 1988 volume-1 third-pass work also recovered or independently corroborated **nine QSYS logical records**. Comparison with 1994-associated evidence was used to check those candidate repairs byte-for-byte. This is a valuable illustration of using a later tape as *independent corroboration*, while recording which bytes were actually read from 1988 and which comparisons came from a different recording.

### Concrete A01 comparison

In our aligned comparison, an overlapping 1988/1994 region of **QSS1.L2924.A01** matched at approximately **99.7368% of bytes**. That is strong evidence of a common underlying structure but also concrete evidence that the files are **not wholly identical**.

An experimental 1994 A01 candidate comprised **32,317,440 bytes placed**, of which **26,841,600 bytes were authentic 1994 evidence** and **5,475,840 bytes were supplied from the 1988 recording**. A further **2,899,968-byte join gap** remained outside the placed candidate. The placed material had **zero conflicts among the selected good target reads**. This is a **research reconstruction**, not a claim that every original 1994 byte was recovered.

A later three-way 1988/1989/1994 comparison offered approximately **1,638,912 bytes** of clean 1988/1989 agreement over part of the 1994 gap, while also identifying **196 conflicting comparisons** in the broader analysis. Agreement is evidence; disagreements must remain explicit and block automatic promotion to “exact original.”

The **1994 volume-1 ending was not successfully observed** in the relevant acquisition, so the exact loss at the volume-1/volume-2 transition remains a significant limit. Volume 2's presence cannot, by itself, establish the bytes missing from volume 1.

### A practical reconstruction confidence hierarchy

1. Exact, complete target block with good status and matching independent rereads.
2. Exact target block from one complete good-status reread with strong structural alignment.
3. Identical reconstruction of the target block from multiple independently captured fragments.
4. Well-aligned but uncorroborated fragments of the target tape.
5. Donor block from another tape with independent, byte-exact evidence of identity in matching surrounding blocks.
6. Donor block chosen on plausibility or merely the same IBM filename.
7. Unknown/missing content.

Levels 5–6 must be marked **borrowed**, not **physically recovered from the target**. The weakest source can determine whether the reconstructed image is historically authentic.

## 9. Other case studies and what they taught us

| Cartridge / effort | Observed acquisition or structural result | Remaining lesson |
|---|---|---|
| **1988 SAVSYS V1** | 1-retry second pass: **5,451 good, 203 suspect, 24 filemarks**; third pass **5,451 good, 159 suspect, 24 filemarks** | Repeated acquisitions and logical-block alignment recover more than any single raw TAP; read counts do not equal IBM blocks. |
| **1988 SAVSYS V2** | **4,237 good, 22 suspect, 138 filemarks**; IBM inventory: **46 files**, their HDR/EOF structures and EOF1 counts consistent | A largely readable tape can still contain locally damaged bytes. |
| **1989 SAVSYS V2** | **4,363 good, 15 suspect, 4,520 reads**; IBM inventory: **47 files** with **141 filemarks**, including an extra PPSIUTIL file | Provides independent evidence for portions of files shared with other sets, while recording legitimate file-level differences. |
| **1994 SAVSYS V1** | **5,285 good, 651 suspect, 22 filemarks**; stopped after repeated zero-byte medium errors in file 22 | No witnessed final closure or EOD; do not invent the volume boundary or missing payload. |
| **1994 SAVSYS V2** | **309 good, 13 suspect, 12 filemarks**, reached observed end-of-data | A volume continuation is useful even when the preceding volume is incomplete. |
| **COBOL/400 R02M00** | Earlier stream attempts repeatedly stopped around file 25; direct SG diagnostics obtained a **7,168-byte suspect fragment** and a following **13,736-byte good fragment**, plus later continuation and tail reads | A targeted continuation can rescue downstream files, but discontinuities and acquisition order must be verified before declaring a full reconstruction. |
| **RPG/400 R02M00** | Stream capture reported **138 tape files, 2,241 records, ~21.90 MiB payload** | A reported successful capture is a useful baseline, not a substitute for independent IBM file and install validation. |

**Real AS/400 testing:** We attempted to use a reconstructed 1988 SAVSYS image on physical B10 hardware. The machine progressed into save/LIC activity, but a later run reached SRC **B68D 6142** during the broader tape sequence. That observation demonstrates substantive progress through the image, **not a verified end-to-end successful restore**. Preserve emulator logs and physical hardware SRCs alongside the exact image hash tested.

## 10. Targeted rereads without losing context

Broad full passes give the best initial alignment evidence, but they can be expensive on fragile tape. After mapping damage, a targeted reread should specify:

- immutable **volume ID**, relevant IBM logical file ID/sequence and suspected logical block range;
- baseline capture/read number and TAP offset;
- known-good boundary before and after the target;
- exact drive position procedure, expected filemarks and verification;
- drive retry count, buffer size and every SCSI command used;
- whether transport was rewound, backspaced, file-spaced or simply continued.

Never assume that **/dev/nst0 mt status** accurately represents the current location after direct **/dev/sg1** reads. Do not use a **--start-file** label as a positioning command.

Earlier recovery code used **mt rewind / fsf / bsfm** to attempt recovery from a failed file. On old QIC hardware, those commands can fail or move unexpectedly; verify the boundary by identifying real labels after the move. If it cannot be verified, mark the resulting segment as having **unknown initial alignment**.

For the COBOL tape we preserved separately numbered probe and continuation batches, then the tail from file 29. Those batches must be joined according to actual read logs and physical moves, **not alphabetically by their temporary directory names or timestamps**.

A useful future enhancement is a targeted-reread planning file containing unresolved ranges, suggested safe anchors, history of attempts and remaining uncertainty. The raw acquisition must remain immutable.

## 11. How to tell when we are finished

Use a **multi-stage status**, not a single “recovered” boolean:

| Stage | Passing criterion |
|---|---|
| **Acquisition** | Complete log and immutable artifacts exist; actual end-of-data observed or a partial stop explicitly recorded. |
| **Forensic integrity** | TAP, journal, suspect sidecars, offsets, ZIP members and checksums validate. |
| **IBM structure** | Files, labels, sequence numbers, filemarks, continuations and trailer counts are coherent. |
| **Logical reconstruction** | Every expected original block has a classified state; conflicts and unknown bytes are identified. |
| **Historical fidelity** | All claimed original target bytes have source-supported provenance; borrowed/substituted bytes are distinguished. |
| **Functional validation** | Intended OS/400 reader can list, install or restore the desired content from the exact tested derivative, with logs. |

A successfully mounted image might pass stage 2 or 3 and fail 4–6. An install may process good early files and fail later. Record the **exact SHA-256 of the image used in each test** so later repairs cannot be confused with earlier trial results.

For the 1988/1989/1994 sets, no single “100% recovered” claim follows from the results documented here. Unresolved original blocks and/or volume transitions remain.

## 12. Making the work reproducible for the team

We should publish, as non-proprietary materials:

1. **The exact active acquisition script** (the November SG_IO version with TDC 4100 retry verification), plus its version/hash and a stable CLI.
2. **Legacy readers**, explicitly labeled experimental/historical (stream reader and earlier read-only SG_IO variant), explaining where their assumptions differ.
3. **TAP + JSONL validator** with synthetic fixtures for good, suspect, filemark, end and odd-length cases.
4. **IBM 80-byte label and file-map parser**, with synthetic sample labels, not copied private backup data.
5. **Logical-block pass aligner and fragment reconciler**, with confidence categories and exhaustive per-block provenance.
6. **Cross-tape comparator** that distinguishes same-source rereads from different physical volumes/releases and reports conflicts.
7. **Manifest schema and example reconstruction**, with reproducible build instructions and output hashes.
8. **Tape/drive registry**, photos, restoration results and an unresolved-targeted-reread queue. Public versions should avoid customer identifiers.
9. **A small test suite / CI**, including false-alignment, ambiguous fragments, zero-byte errors, incorrect TAP trailer, odd padding, and donor conflicts.
10. **Compatibility notes** for SIMH/E11/AWS, ZuluSCSI, and Solstice, linked to the exact firmware/image versions actually tested.

Do not add a permissive software license without first deciding what third-party code, if any, is incorporated. Do not commit raw IBM program media or private customer data.

## 13. Glossary

- **Read:** one host-issued SCSI READ command; it is *not necessarily* one original tape block.
- **Record / original logical block:** a data block as recorded in the original tape's logical structure; one may produce several returned fragments after damage.
- **Fragment:** bytes attributable to some portion of a logical record, not yet sufficient evidence of the complete record.
- **Suspect:** nonempty data returned along with a medium error or otherwise lacking sufficient integrity assurance.
- **Possible gap:** an error where the drive supplied no bytes and the amount of lost original data is not established.
- **Filemark:** a tape-level separator. Not identical to an IBM EOF label.
- **IBM logical file:** a labeled AS/400 tape entity with identifiers, sequences and possibly volume continuation.
- **EOV:** IBM End-of-Volume label, distinct from an underlying end-of-data/EOM condition.
- **TAP:** record-framed image format; it cannot by itself prove tape readability or original-byte authenticity.
- **Derivative:** reconstructed output with traceable, immutable source captures and a repair manifest.
- **Borrowed block:** material sourced from a *different recording* because the target tape lacked direct evidence. Its origin must be disclosed.
- **Restore-tested:** the exact derivative was processed successfully by the specified target, not merely that a parser accepted it.

## 14. Evidence sources and open questions

This document was compiled from the acquisition source scripts, the **November 19, 2026 tape archive inventory**, saved read/retry transcripts, and the subsequent November 20–22 SAVSYS/COBOL comparison and B10 testing notes. Publicly released scripts, manifests and synthetic fixtures should provide independently reproducible references to each measurement as they are added.

**Questions that remain open or require additional direct evidence:**

- Which internal motion/retry sequence does the TDC 4100 execute for each error and how does it determine the position of the next READ?
- Exactly which “good after bad” reads are tails of the same original logical record versus later records?
- Which 1988-versus-1989-versus-1994 A01 ranges are byte-identical, and which are legitimate release changes?
- Can we resolve the remaining 1988 volume-1 suspect blocks and the 1994 volume-1 ending through targeted reads or independently verified donors?
- Can COBOL’s partial batches be joined without unknown gaps and then validated against its original IBM file/trailer structure?
- Can additional media and a physical B10 complete an end-to-end restored/installed-system test for the final selected derivatives?

Maintain a durable answer/evidence record for each question. New evidence should update the **dated case study and derivative manifest**, not retroactively overwrite an older result.

---

**Preservation principle:** It is better to publish an accurately described, partially recovered tape—with exact error locations and independently verifiable evidence—than a convenient, apparently complete image whose unknown or substituted bytes have been hidden.
