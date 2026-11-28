import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ibm_save_objects import headers


def synthetic_header(name, type_code):
    data = bytearray(512)
    data[:4] = b"\xff" * 4
    data[4:34] = name.ljust(30).encode("cp037")
    data[34:36] = bytes.fromhex(type_code)
    data[154:171] = "OBJECT DESCRIPTOR".encode("cp037")
    return bytes(data)


class SaveHeaderTests(unittest.TestCase):
    def test_aligned_program_and_internal_offset(self):
        data = bytes(512) + synthetic_header("TESTPGM", "0201")
        (header,) = list(headers(data, base=-1024))
        self.assertEqual(header["at"], -512)
        self.assertEqual(header["object_type"], "*PGM")
        self.assertEqual(header["name"], "TESTPGM")
        self.assertTrue(header["descriptor"])

    def test_unaligned_reference_and_unknown_type(self):
        data = b"\0" + synthetic_header("TESTOBJ", "1432")
        self.assertEqual(list(headers(data)), [])
        (header,) = list(headers(data, aligned=False))
        self.assertEqual(header["type_code"], "1432")
        self.assertIsNone(header["object_type"])

    def test_false_sentinel_ignored(self):
        self.assertEqual(list(headers(b"\xff" * 512)), [])
