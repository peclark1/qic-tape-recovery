# IBM tape SCB audit

Run the report-only audit against a complete, IBM-labelled SIMH tape.

```sh
python3 scripts/ibm_scb.py capture.tap > scb-audit.json
python3 -m unittest discover -s tests -v
```

The audit applies the [IBM CVTSC string rules](https://www.ibm.com/docs/en/i/7.5.0?topic=c-convert-sna-character-cvtsc) to whole payloads. It requires exact consumption of the compressed input and exactly 24,576 expanded bytes. It reports the first invalid input and expanded offsets. Length words and SIMH odd-byte padding are excluded from the SCB input. Pass `prime=0x40` explicitly to the Python decoder for the G1749 profile. The audit does not need the prime byte because it checks lengths and syntax.

A payload that passes the SCB grammar is structurally plausible. A failing 24,576-byte payload is classified by its raw size only. Other failures are reported as unclassified. The report retains the original flag status and one-based observed frame numbering within a three-mark file group. After a split read, the observed frame number and IBM logical record number may differ. The report lists suspect and unrecognized label frames and exposes declared and observed counts. It makes no changes to the tape.

The six synthetic tests check all three SCB operations, bad count and control values, truncated operands, output bounds, precise error offsets, and SIMH framing with a flagged failure. No tape payloads are fixtures.
