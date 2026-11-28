"""Synthetic fixtures; no original tape contents."""
import unittest
from test_recovery_toolkit import frame, mark, label, t
import tempfile
from pathlib import Path
import reblock as r

def image(parts, count):
    return (frame("VOL1TEST01".ljust(80).encode("cp037")) +
            frame(label("HDR1")) + mark() +
            b"".join(frame(data, suspect) for data, suspect in parts) +
            mark() + frame(label("EOF1", count)) + mark() + mark(t.END))

class FragmentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)

    def put(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return p
    def test_fixed_two_and_three_fragments(self):
        parts = [(b"a"*512, True), (b"b"*24064, False),
                 (b"c"*1024, True), (b"d"*512, True), (b"e"*23040, False)]
        src = self.put("in.tap", image(parts, 2))
        out, manifest = self.d/"out.tap", self.d/"manifest.json"
        report = r.reblock(src, out, manifest)
        self.assertEqual(report["remaining_error_flags"], 2)
        self.assertEqual(report["files"][0]["projected"], 2)
        self.assertEqual(out.read_bytes(), image([
            (b"a"*512+b"b"*24064, True),
            (b"c"*1024+b"d"*512+b"e"*23040, True)], 2))
        self.assertEqual(src.read_bytes(), image(parts, 2))
        with self.assertRaises(ValueError):
            r.reblock(src, out, manifest)

    def test_variable_opt_in_and_odd_padding(self):
        parts = [(b"a"*512, True), (b"b"*1001, False)]
        src = self.put("in.tap", image(parts, 1))
        self.assertEqual(r.audit(src)["files"][0]["remaining_excess"], 1)
        out, manifest = self.d/"out.tap", self.d/"manifest.json"
        result = r.reblock(src, out, manifest, allow_variable=True)
        self.assertEqual(result["files"][0]["groups"][0]["kind"], "variable-inferred")
        self.assertEqual(out.read_bytes(), image([(b"a"*512+b"b"*1001, True)], 1))

    def test_overlap_not_joined(self):
        src = self.put("in.tap", image([(b"a"*512, True),(b"b"*24576, False)],1))
        self.assertEqual(r.audit(src)["files"][0]["remaining_excess"], 1)
        with self.assertRaises(ValueError):
            r.reblock(src, self.d/"out", self.d/"manifest", allow_variable=True)
        self.assertFalse((self.d/"out").exists())

    def test_matching_count_not_modified(self):
        src = self.put("in.tap", image([(b"a"*512, True),(b"b"*24064, False)],2))
        self.assertEqual(r.audit(src)["files"][0]["groups"], [])

    def test_excess_candidates_rejected(self):
        src = self.put("in.tap", image([(b"a"*512, True),(b"b"*24064, False)]*2,3))
        with self.assertRaises(ValueError):
            r.audit(src)

    def test_full_suspect_retained(self):
        src = self.put("in.tap", image([(b"a"*24576, True),(b"b"*1001, False)],2))
        out, manifest = self.d/"out.tap", self.d/"manifest.json"
        r.reblock(src,out,manifest,allow_variable=True)
        self.assertEqual(src.read_bytes(),out.read_bytes())

    def test_incomplete_input_rejected(self):
        src = self.put("in.tap", image([(b"a"*512,True)],1)[:-4])
        with self.assertRaises(ValueError):
            r.audit(src)
