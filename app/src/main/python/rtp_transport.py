"""RTP media framing with evidence of a real packet stream.

A single RTP-looking header inside an encrypted media record is not enough:
require three consecutive sequence numbers, the same SSRC, payload type and
framing offset, before treating its payload as a camera stream.
No raw video or network identifiers are logged.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RtpPacket:
    base: int
    seq: int
    ssrc: int
    payload_type: int
    payload: bytes


class RtpVideoBridge:
    OFFSETS = (0, 4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 64)

    def __init__(self):
        self.header_candidates = 0
        self.validated_packets = 0
        self.fragmented = 0
        self.completed_nals = 0
        self._tracks = {}
        self._nal_fragment = None
        self._nal_codec = None
        self._fragment_seq = None

    @staticmethod
    def _plausible(payload):
        if len(payload) < 2 or payload[0] & 0x80:
            return False
        avc_type = payload[0] & 31
        hevc_type = (payload[0] >> 1) & 63
        hevc_valid = (payload[1] & 7) != 0
        return avc_type in (1, 5, 6, 7, 8, 9, 24, 28) or (
            hevc_valid and hevc_type in (1, 19, 20, 21, 32, 33, 34, 35, 39, 40, 48, 49)
        )

    @classmethod
    def _parse_at(cls, raw, base):
        if len(raw) < base+14 or raw[base] >> 6 != 2:
            return None
        payload_type = raw[base+1] & 127
        if not 96 <= payload_type <= 127:
            return None
        cc = raw[base] & 15
        off = base + 12 + 4*cc
        if off >= len(raw):
            return None
        if raw[base] & 16:
            if off+4 > len(raw):
                return None
            words = int.from_bytes(raw[off+2:off+4], "big")
            if words > 32:
                return None
            off += 4 + words*4
        if off >= len(raw):
            return None
        end = len(raw)
        if raw[base] & 32:
            pad = raw[-1]
            if pad == 0 or pad >= end-off:
                return None
            end -= pad
        payload = raw[off:end]
        if not cls._plausible(payload):
            return None
        return RtpPacket(base, int.from_bytes(raw[base+2:base+4], "big"),
                         int.from_bytes(raw[base+8:base+12], "big"),
                         payload_type, payload)

    def push(self, raw):
        """Return zero or more (codec, Annex-B NAL) tuples from validated RTP."""
        matches = [packet for base in self.OFFSETS
                   if (packet := self._parse_at(raw,base)) is not None]
        if not matches:
            return []
        def strength(packet):
            track = self._tracks.get((packet.base,packet.payload_type,packet.ssrc))
            if track is None:
                return 0
            continuity = ((packet.seq - track[0]) & 65535) == 1
            return (4 if track[2] else 2) + (1 if continuity else 0)
        selected = max(matches,key=strength)
        self.header_candidates += 1
        key = (selected.base, selected.payload_type, selected.ssrc)
        track = self._tracks.get(key)
        if track is None:
            self._tracks[key] = [selected.seq, deque([selected], maxlen=3), False]
            # Do not accumulate unbounded fake SSRCs.
            if len(self._tracks) > 48:
                self._tracks.pop(next(iter(self._tracks)))
            return []
        prev, buffered, confirmed = track
        delta = (selected.seq-prev) & 65535
        if not confirmed:
            if delta != 1:
                buffered.clear()
                buffered.append(selected)
                track[0] = selected.seq
                return []
            buffered.append(selected)
            track[0] = selected.seq
            if len(buffered) < 3:
                return []
            track[2] = True
            ready = list(buffered)
            buffered.clear()
        else:
            if delta != 1:
                # Retransmission/gap: reset fragmented NAL; do not trust a
                # partial frame, but a healthy stream can resume.
                self._nal_fragment = None
            track[0] = selected.seq
            ready = [selected]
        self.validated_packets += len(ready)
        out = []
        for packet in ready:
            out.extend(self._depacketize(packet.payload, packet.seq))
        return out

    @staticmethod
    def _codec(payload):
        avc = payload[0] & 31
        hevc = (payload[0] >> 1) & 63
        if avc in (5, 7, 8, 24, 28):
            return "avc"
        if hevc in (19, 20, 21, 32, 33, 34, 35, 39, 40, 48, 49) and (payload[1] & 7):
            return "hevc"
        if avc in (1, 6, 9):
            return "avc"
        if hevc == 1 and (payload[1] & 7):
            return "hevc"
        return None

    def _depacketize(self, payload, seq):
        codec = self._codec(payload)
        if not codec:
            return []
        if codec == "avc":
            kind = payload[0] & 31
            if kind == 24:  # STAP-A aggregate.
                results = []
                pos = 1
                while pos+2 <= len(payload):
                    size = int.from_bytes(payload[pos:pos+2], "big")
                    pos += 2
                    if size < 1 or size > 65535 or pos+size > len(payload):
                        return []
                    results.append(("avc", b"\x00\x00\x00\x01"+payload[pos:pos+size]))
                    pos += size
                self.completed_nals += len(results)
                return results
            if kind == 28 and len(payload) > 2:  # FU-A fragment.
                self.fragmented += 1
                kind = payload[1] & 31
                start, end = bool(payload[1] & 128), bool(payload[1] & 64)
                if start:
                    self._nal_fragment = bytearray(
                        b"\x00\x00\x00\x01" + bytes([(payload[0] & 224) | kind]) +
                        payload[2:]
                    )
                    self._nal_codec = "avc"
                    self._fragment_seq = seq
                elif (self._nal_codec == "avc" and self._nal_fragment is not None and
                      seq == (self._fragment_seq+1) & 65535):
                    self._nal_fragment.extend(payload[2:])
                    self._fragment_seq = seq
                else:
                    self._nal_fragment = None
                if end and self._nal_fragment is not None:
                    done = bytes(self._nal_fragment)
                    self._nal_fragment = None
                    self.completed_nals += 1
                    return [("avc", done)]
                return []
        else:
            kind = (payload[0] >> 1) & 63
            if kind == 49 and len(payload) > 3:  # HEVC FU.
                self.fragmented += 1
                start, end = bool(payload[2] & 128), bool(payload[2] & 64)
                if start:
                    header = bytes([(payload[0] & 129) | ((payload[2] & 63) << 1),
                                    payload[1]])
                    self._nal_fragment = bytearray(b"\x00\x00\x00\x01"+header+payload[3:])
                    self._nal_codec = "hevc"
                    self._fragment_seq = seq
                elif (self._nal_codec == "hevc" and self._nal_fragment is not None and
                      seq == (self._fragment_seq+1) & 65535):
                    self._nal_fragment.extend(payload[3:])
                    self._fragment_seq = seq
                else:
                    self._nal_fragment = None
                if end and self._nal_fragment is not None:
                    done = bytes(self._nal_fragment)
                    self._nal_fragment = None
                    self.completed_nals += 1
                    return [("hevc", done)]
                return []
            if kind == 48:  # AP not yet implemented, do not pass corrupt bytes.
                return []
        self.completed_nals += 1
        return [(codec,b"\x00\x00\x00\x01"+payload)]

    def safe_stats(self):
        return ("RTP candidati: "+str(self.header_candidates)+
                " | RTP verificati: "+str(self.validated_packets)+
                " | frammenti FU: "+str(self.fragmented)+
                " | NAL ricostruite: "+str(self.completed_nals))
