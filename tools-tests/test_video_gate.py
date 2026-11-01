"""Tests for conservative codec recognition. No real camera data."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
from video_gate import VideoFormatGate, ANNEX_B


class VideoGateTests(unittest.TestCase):
    def test_random_looking_headers_never_trigger_codec(self):
        gate=VideoFormatGate()
        for _ in range(1000):
            self.assertIsNone(gate.feed(ANNEX_B+b"\x65"+b"nonsense"+b"0"*20))
            self.assertIsNone(gate.feed(ANNEX_B+b"\x26"+b"nonsense"+b"0"*20))
        self.assertIsNone(gate.codec)

    def test_h264_requires_sps_pps_and_idr(self):
        gate=VideoFormatGate()
        self.assertIsNone(gate.feed(ANNEX_B+bytes.fromhex("6742001fe58868")))
        self.assertIsNone(gate.feed(ANNEX_B+bytes.fromhex("68ce06e2")))
        sample=gate.feed(ANNEX_B+bytes.fromhex("658880") + b"x"*30)
        self.assertIsNotNone(sample)
        self.assertEqual(sample[0],"avc")
        self.assertIn(bytes.fromhex("6742001f"),sample[1])
        self.assertEqual(gate.codec,"avc")

    def test_missing_sps_not_accepted(self):
        gate=VideoFormatGate()
        gate.feed(ANNEX_B+bytes.fromhex("68ce06e2"))
        self.assertIsNone(gate.feed(ANNEX_B+b"\x65"+b"n"*50))
        self.assertIsNone(gate.codec)

if __name__=="__main__":
    unittest.main()
