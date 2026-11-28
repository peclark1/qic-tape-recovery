import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ibm_scb import BLOCK_SIZE, SCBError, audit, decode


def record(payload, *, flagged=False):
    word = struct.pack("<I", len(payload) | (0x80000000 if flagged else 0))
    return word + payload + bytes(len(payload) % 2) + word


def label(text):
    return record(text.ljust(80).encode("cp037"))


class StringCompressionTests(unittest.TestCase):
    def test_literal_prime_and_duplicate(self):
        encoded = b"\x02\x00\x40\x83\xc4\xaa"
        self.assertEqual(decode(encoded, prime=0x40, expected=9),
                         b"\x00" + b"\x40"*4 + b"\xaa"*4)

    def test_maximum_count_and_custom_prime(self):
        self.assertEqual(decode(b"\xbf", prime=0x17, expected=63), b"\x17"*63)

    def test_invalid_control_and_truncated_operand(self):
        for value, reason in ((b"\x40", "reserved"), (b"\x80", "zero"),
                              (b"\x02a", "truncated"), (b"\xc1", "truncated")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SCBError, reason):
                    decode(value, prime=0, expected=2)

    def test_short_overrun_and_full_stream_consumption(self):
        for value, reason in ((b"\x81", "short output"), (b"\x83", "output overrun"),
                              (b"\x82\x00", "zero count")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(SCBError, reason):
                    decode(value, prime=0, expected=2)

    def test_input_and_output_error_offsets(self):
        with self.assertRaises(SCBError) as caught:
            decode(b"\x83\x02ab\x00", prime=0, expected=6)
        self.assertEqual((caught.exception.offset, caught.exception.produced), (4, 5))

    def test_tape_audit_distinguishes_raw_size_and_flagged_invalid(self):
        mark = bytes(4)
        n, remainder = divmod(BLOCK_SIZE, 63)
        scb = b"\xbf"*n + bytes([0x80 + remainder])
        identity = "QSYS".ljust(17) + "TST00100010001"
        tape = (label("VOL1TST001") + label("HDR1"+identity) + mark +
                record(scb) + record(bytes(BLOCK_SIZE)) + record(b"\x00", flagged=True) +
                mark + label(("EOF1"+identity).ljust(54)+"000003") + mark +
                struct.pack("<I", 0xffffffff))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.tap"
            path.write_bytes(tape)
            result = audit(path)
            file, = result["files"]
            self.assertEqual(result["volume"], "TST001")
            self.assertEqual(file["declared"], 3)
            self.assertEqual(file["counts"], {"scb_clean": 1, "raw_size_clean": 1,
                                             "unclassified_flagged": 1})
            self.assertEqual(file["unclassified"][0]["record"], 3)


if __name__ == "__main__":
    unittest.main()
