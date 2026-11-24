import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import recovery_toolkit as t

def frame(data, suspect=False):
    w = struct.pack("<I", len(data) | (t.ERR if suspect else 0))
    return w + data + b"\0" * (len(data) % 2) + w

def mark(n=0):
    return struct.pack("<I", n)

def label(kind, count=0):
    s = kind + "SYNTHETIC".ljust(17) + "TEST01" + "00010001"
    return (s.ljust(54) + str(count).zfill(6)).ljust(80).encode("cp037")

def tape(data, suspect=False):
    return (frame("VOL1TEST01".ljust(80).encode("cp037")) +
            frame(label("HDR1")) + mark() + frame(b"left") +
            frame(data, suspect) + frame(b"right") + mark() +
            frame(label("EOF1", 3)) + mark() + mark(t.END))

class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def put(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return p

    def test_odd_and_trailer(self):
        p = self.put("x.tap", frame(b"abc") + mark(t.END))
        self.assertEqual(list(t.frames(p))[0][2], b"abc")
        p.write_bytes(frame(b"abc")[:-1] + b"\xff")
        with self.assertRaises(ValueError):
            list(t.frames(p))

    def test_inventory(self):
        p = self.put("a.tap", tape(b"bad", True))
        f, = t.inventory(p)
        self.assertTrue(f["count_matches"])
        self.assertTrue(f["identity_matches"])
        self.assertTrue(f["records"][1]["suspect"])

    def test_reconstruct(self):
        a = self.put("a.tap", tape(b"bad", True))
        b = self.put("b.tap", tape(b"new"))
        out, manifest = self.d / "out.tap", self.d / "manifest.json"
        original = a.read_bytes()
        report = t.reconstruct(a,b,out,manifest,True)
        self.assertEqual(len(report["changes"]), 1)
        self.assertEqual(report["remaining_error_flags"], 1)
        self.assertEqual(a.read_bytes(), original)
        self.assertEqual(out.read_bytes(), tape(b"new", True))
        with self.assertRaises(ValueError):
            t.reconstruct(a,b,out,manifest,True)

    def test_cross_tape_read_only(self):
        a = self.put("a.tap", tape(b"bad", True))
        b = self.put("b.tap", tape(b"new"))
        self.assertEqual(t.candidates(a,b)[0]["classification"], "candidate")
        with self.assertRaises(ValueError):
            t.reconstruct(a,b,self.d/"out",self.d/"m",False)

    def test_unequal_length(self):
        a = self.put("a.tap", tape(b"bad", True))
        b = self.put("b.tap", tape(b"longer"))
        self.assertEqual(t.candidates(a,b,True), [])

    def test_conflict(self):
        a = self.put("a.tap", tape(b"old"))
        b = self.put("b.tap", tape(b"new"))
        self.assertEqual(t.candidates(a,b,True)[0]["classification"], "conflict")

    def test_capture_validation(self):
        image = self.put("capture.tap", frame(b"abc") + frame(b"bad", True) + mark() + mark(t.END))
        self.put("read-000000002.bin", b"bad")
        self.put("SHA256SUMS", (t.digest(image)+"  capture.tap\n").encode())
        events = [{"event":"start","file":0,"buffer":32768}]
        for i, (kind, offset, n, file) in enumerate([
            ("record",0,3,0), ("suspect_record",12,3,0),
            ("possible_gap",24,0,0), ("filemark",24,0,0),
            ("end_of_data",28,0,1)], 1):
            e = dict(event=kind, read=i, offset=offset, bytes=n, file=file,
                     status=0 if i==1 else 2, host=0, driver=0,
                     residual=32768-n, sense="")
            if i==2:
                e["payload_file"]="read-000000002.bin"
            events.append(e)
        self.put("capture.jsonl", "\n".join(map(json.dumps,events)).encode())
        self.assertTrue(t.validate(self.d)["observed_eod"])
        self.put("read-000000002.bin", b"BAD")
        with self.assertRaises(ValueError):
            t.validate(self.d)

if __name__ == "__main__":
    unittest.main()
