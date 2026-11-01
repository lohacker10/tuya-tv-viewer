"""Strict, codec-agnostic on-device AVC/HEVC validation.

Never prints or persists camera video. A lone NAL-looking byte pattern is NOT
proof of a codec. Require a coherent parameter set and keyframe before emitting
anything to Android MediaCodec.
"""
from __future__ import annotations

H264_PROFILES = frozenset({44, 66, 77, 83, 86, 88, 100, 110, 118, 122, 128, 134, 135, 138, 139, 244})
ANNEX_B = b"\x00\x00\x00\x01"


def split_nalus(blob: bytes):
    """Return at most 64 NAL units from a bounded Annex B buffer."""
    matches = []
    pos = 0
    limit = min(len(blob), 524288)
    while pos < limit - 4 and len(matches) < 64:
        i = blob.find(b"\x00\x00\x01", pos, limit)
        if i < 0:
            break
        # 4-byte start code has a zero just before the 3-byte signature.
        start = i-1 if i > 0 and blob[i-1] == 0 else i
        payload = i+3
        if payload < limit and blob[payload] == 0 and payload+1 < limit and blob[payload+1] == 1:
            payload += 2
        if payload >= limit:
            break
        matches.append((start,payload))
        pos = payload
    for idx, (_start, payload) in enumerate(matches):
        end = matches[idx+1][0] if idx+1 < len(matches) else limit
        if end > payload:
            yield blob[payload:end]


class VideoFormatGate:
    """Only publish AVC/HEVC when parameter sets AND keyframe are consistent."""

    def __init__(self):
        self.codec = None
        self.h264_sps = None
        self.h264_pps = None
        self.hevc_vps = None
        self.hevc_sps = None
        self.hevc_pps = None
        self.candidates = 0
        self.config_units = 0
        self.confirmed_samples = 0
        self.avc_idr_candidates = 0
        self.hevc_idr_candidates = 0

    def feed(self, blob: bytes):
        if not blob:
            return None
        raw_units = list(split_nalus(blob))
        if not raw_units:
            return None
        self.candidates += len(raw_units)
        if self.codec:
            self.confirmed_samples += 1
            return self.codec,blob
        for nal in raw_units:
            if len(nal) < 4:
                continue
            avc_type = nal[0] & 31
            hevc_type = (nal[0] >> 1) & 63

            # H264 SPS has NAL type 7, known profile IDC and plausible level.
            if avc_type == 7 and len(nal) >= 6 and nal[1] in H264_PROFILES and 1 <= nal[3] <= 63:
                self.h264_sps = ANNEX_B + nal
                self.config_units += 1
                continue
            if avc_type == 8 and len(nal) >= 4 and nal[0] == 0x68:
                self.h264_pps = ANNEX_B + nal
                self.config_units += 1
                continue
            # HEVC NAL unit header: forbidden_zero_bit=0, temporal_id_plus1>0.
            if len(nal) >= 6 and (nal[0] & 0x80) == 0 and (nal[1] & 7) != 0:
                if hevc_type == 32:
                    self.hevc_vps = ANNEX_B + nal
                    self.config_units += 1
                    continue
                if hevc_type == 33:
                    self.hevc_sps = ANNEX_B + nal
                    self.config_units += 1
                    continue
                if hevc_type == 34:
                    self.hevc_pps = ANNEX_B + nal
                    self.config_units += 1
                    continue
            if avc_type == 5 and len(nal) >= 16:
                self.avc_idr_candidates += 1
            if avc_type == 5 and len(nal) >= 16 and self.h264_sps and self.h264_pps:
                self.codec = "avc"
                self.confirmed_samples += 1
                return "avc",self.h264_sps+self.h264_pps+ANNEX_B+nal
            if hevc_type in (19,20) and len(nal) >= 16 and (nal[1] & 7):
                self.hevc_idr_candidates += 1
            if hevc_type in (19,20) and len(nal) >= 16 and self.hevc_vps and self.hevc_sps and self.hevc_pps:
                self.codec = "hevc"
                self.confirmed_samples += 1
                return "hevc",self.hevc_vps+self.hevc_sps+self.hevc_pps+ANNEX_B+nal
        return None

    def safe_stats(self):
        return ("NAL candidati: "+str(self.candidates)+
                " | config candidati: "+str(self.config_units)+
                " | IDR AVC: "+str(self.avc_idr_candidates)+
                " | IDR HEVC: "+str(self.hevc_idr_candidates)+
                " | SPS AVC: "+str(bool(self.h264_sps))+
                " | PPS AVC: "+str(bool(self.h264_pps))+
                " | VPS HEVC: "+str(bool(self.hevc_vps))+
                " | SPS HEVC: "+str(bool(self.hevc_sps))+
                " | PPS HEVC: "+str(bool(self.hevc_pps))+
                " | codec verificato: "+(self.codec or "nessuno"))
