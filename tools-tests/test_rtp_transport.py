"""Pure-Python RTP regression tests, no camera video or credentials."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"app/src/main/python"))
from rtp_transport import RtpVideoBridge
from video_gate import VideoFormatGate


def pkt(seq, payload, ssrc=123456, pt=96, offset=0):
    header=(bytes([0x80,pt])+
            seq.to_bytes(2,"big")+(12345).to_bytes(4,"big")+
            ssrc.to_bytes(4,"big"))
    return bytes(offset)+header+payload


class RtpBridgeTests(unittest.TestCase):
    def test_h264_sps_pps_and_idr_are_reassembled(self):
        b=RtpVideoBridge()
        gate=VideoFormatGate()
        sps=bytes.fromhex("6742001fe58868")
        pps=bytes.fromhex("68ce06e2")
        idr=bytes.fromhex("658880")+b"x"*28
        out=[]
        out += b.push(pkt(100,sps))
        out += b.push(pkt(101,pps))
        out += b.push(pkt(102,idr))
        self.assertEqual(len(out),3)
        self.assertEqual(b.validated_packets,3)
        final=None
        for codec,data in out:
            self.assertEqual(codec,"avc")
            final=gate.feed(data) or final
        self.assertIsNotNone(final)
        self.assertEqual(final[0],"avc")
        self.assertEqual(gate.codec,"avc")

    def test_h264_fu_a_fragment_complete(self):
        b=RtpVideoBridge()
        b.push(pkt(10,b"\x67\x42\x00\x1f\xe5\x88\x68"))
        b.push(pkt(11,b"\x68\xce\x06\xe2"))
        b.push(pkt(12,b"\x41"+b"a"*12))
        payload=b"\x65"+b"abcdef123456"
        start=b"\x7c\x85"+payload[1:8]
        end=b"\x7c\x45"+payload[8:]
        self.assertEqual(b.push(pkt(13,start)),[])
        assembled=b.push(pkt(14,end))
        self.assertEqual(len(assembled),1)
        self.assertEqual(assembled[0][0],"avc")
        self.assertEqual(assembled[0][1],b"\x00\x00\x00\x01"+payload)

    def test_random_looking_headers_do_not_count_as_validated(self):
        b=RtpVideoBridge()
        for n in range(300):
            b.push(pkt(n,b"\x65"+b"x"*24,ssrc=100000+n))
        self.assertEqual(b.validated_packets,0)
        self.assertEqual(b.completed_nals,0)

    def test_nonsequential_same_stream_is_not_confirmed(self):
        b=RtpVideoBridge()
        for i in range(10):
            b.push(pkt(i*10,b"\x65"+b"x"*24))
        self.assertEqual(b.validated_packets,0)

    def test_rtp_at_nonzero_offset(self):
        b=RtpVideoBridge()
        for seq in [100,101,102]:
            x=b.push(pkt(seq,b"\x67\x42\x00\x1f\xe5\x88\x68",offset=20))
        self.assertEqual(len(x),3)
        self.assertEqual(b.validated_packets,3)

if __name__=="__main__":
    unittest.main()
