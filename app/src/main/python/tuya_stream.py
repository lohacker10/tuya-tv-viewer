"""Native Tuya Smart live video attempt using the proven Java RTC gateway.

Experimental MJPEG P2P media engine by roquerodrigo (MIT, v0.1.1).
Direct on-device streaming: no NAS, relay server of ours, or RTSP proxy.
Only stage and exception categories are passed to the TV UI (no secrets).
"""
import asyncio
import base64
import hashlib
import json
import logging
import time
import re

_loop = None
_stopping = None

def stop():
    global _loop, _stopping
    if _loop is not None and _stopping is not None:
        _loop.call_soon_threadsafe(_stopping.set)

def _type(exc):
    return type(exc).__name__[:65]


def _codec_annex_b(data):
    """Find Annex B NALs after a bounded proprietary media header."""
    limit=min(len(data), 128 * 1024)
    cursor=0
    while cursor < limit - 5:
        i=data.find(b"\x00\x00\x01",cursor,limit)
        if i < 0:
            return None,None
        head=i+3
        if head < limit and data[head] == 0:
            if head+1 < limit and data[head+1] == 1:
                head += 2
            else:
                cursor=i+3
                continue
        if head >= len(data):
            return None,None
        b=data[head]
        if not (b & 0x80) and (b & 31) in (1,5,6,7,8,9):
            return "avc", i
        if not (b & 0x80) and head+1 < len(data) and \
           ((b >> 1) & 63) in (19,20,21,32,33,34,35,39,40) and \
           (data[head+1] & 7) != 0:
            return "hevc", i
        cursor=i+3
    return None,None


class RtpVideoBridge:
    """Convert framed RTP H264/H265 NAL or FU packets into Annex B access units.

    The source-specific envelope has to be identified first; use this parser
    only on bytes which match RTP v2 and a plausible video NAL type.
    """
    def __init__(self):
        self.rtp_count=0
        self.fragmented=0
        self.codec=None
        self.fragment=None
        self.last_seq=None

    def parse(self, data):
        for base in (0,4,8,12,16,20,24,28,32,40,48,64):
            if len(data)<base+16 or data[base]>>6!=2:
                continue
            if data[base+1]&127 < 96:
                continue
            cc=data[base]&15
            header=base+12+4*cc
            if data[base] & 0x10:
                if len(data)<header+4:continue
                ext_words=int.from_bytes(data[header+2:header+4],"big")
                if ext_words>32:continue
                header+=4+4*ext_words
            if header>=len(data):continue
            raw=data[header:]
            nal=raw[0]&31
            hevc_type=(raw[0]>>1)&63
            if nal not in tuple(range(1,24))+(24,28) and \
               hevc_type not in tuple(range(0,48))+(49,):
                continue
            codec="avc" if nal in tuple(range(1,24))+(24,28) else "hevc"
            seq=int.from_bytes(data[base+2:base+4],"big")
            self.rtp_count+=1
            if codec=="avc":
                if nal==28 and len(raw)>=3:
                    self.fragmented+=1
                    start=bool(raw[1]&0x80)
                    end=bool(raw[1]&0x40)
                    if start:
                        self.fragment=bytearray(b"\x00\x00\x00\x01"+
                            bytes([(raw[0]&0xE0)|(raw[1]&0x1f)])+raw[2:])
                    elif self.fragment is not None and (
                        self.last_seq is None or seq==(self.last_seq+1)&65535):
                        self.fragment.extend(raw[2:])
                    else:
                        self.fragment=None
                    self.last_seq=seq
                    if end and self.fragment is not None:
                        frame=bytes(self.fragment)
                        self.fragment=None
                        return "avc",frame
                    return codec,None
                if nal==24:
                    return codec,None
            elif hevc_type==49 and len(raw)>=4:
                self.fragmented+=1
                start=bool(raw[2]&0x80)
                end=bool(raw[2]&0x40)
                if start:
                    nal_header=bytes([((raw[0]&0x81)|((raw[2]&63)<<1)),raw[1]])
                    self.fragment=bytearray(b"\x00\x00\x00\x01"+nal_header+raw[3:])
                elif self.fragment is not None and (
                    self.last_seq is None or seq==(self.last_seq+1)&65535):
                    self.fragment.extend(raw[3:])
                else:
                    self.fragment=None
                self.last_seq=seq
                if end and self.fragment is not None:
                    frame=bytes(self.fragment)
                    self.fragment=None
                    return "hevc",frame
                return codec,None
            self.last_seq=seq
            return codec,b"\x00\x00\x00\x01"+raw
        return None,None


def _avcc_nal(data):
    """Recognize length-prefixed H.264/H.265 NAL units behind small headers."""
    for offset in (0,4,8,12,16,20,24,28,32,40,48,64):
        if len(data)<offset+12:
            continue
        length=int.from_bytes(data[offset:offset+4],"big")
        if length<8 or length>512*1024 or offset+4+length>len(data):
            continue
        payload=data[offset+4:offset+4+length]
        nal=payload[0]&31
        if nal in (1,5,6,7,8,9):
            return "avc",b"\x00\x00\x00\x01"+payload
        hevc=(payload[0]>>1)&63
        if hevc in (19,20,21,32,33,34,35,39,40) and len(payload)>2:
            return "hevc",b"\x00\x00\x00\x01"+payload
    return None,None


def _rtc_dict(data):
    """Unwrap nested Tuya result structures without showing or logging secrets."""
    if isinstance(data, dict):
        if isinstance(data.get("p2pConfig"), dict):
            return data
        for value in data.values():
            found = _rtc_dict(value)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _rtc_dict(value)
            if found is not None:
                return found
    return None

async def _run(sid, ecode, uid, region, install_id, device_id,
               local_key, client_id, composite, ch_key, events):
    global _loop, _stopping
    _loop = asyncio.get_running_loop()
    _stopping = asyncio.Event()
    logging.getLogger("tuya_ipc_p2p_sdk").setLevel(logging.CRITICAL)

    from tuya_ipc_p2p_sdk import MqttIdentity, StreamConfig
    from tuya_ipc_p2p_sdk.stream_session import StreamSession
    from tuya_ipc_p2p_sdk.crypto import decrypt_record
    from tuya_ipc_p2p_sdk.control import is_control
    from tuya_ipc_p2p_sdk.media import extract_media_packets

    tail = hashlib.md5(
        (hashlib.md5(client_id.encode()).hexdigest() + ecode).encode()
    ).hexdigest()[-16:]
    mqtt_user = "p1000018_v1_%s_%s_mb_%s%s" % (client_id, ch_key, sid, tail)
    mqtt_password = hashlib.md5(
        (hashlib.md5(composite.encode()).hexdigest() + ecode).encode()
    ).hexdigest()[8:24]
    mqtt_client_id = "com.tuya.smart_mb_%s_%s_DEFAULT" % (
        install_id,
        hashlib.md5((uid + "sdkfasodifca").encode()).hexdigest()
    )
    identity = MqttIdentity(
        "m1-" + region + ".lifeaiot.com",
        8883, mqtt_client_id, mqtt_user, mqtt_password
    )

    events.onStatus("Richiesta nuova configurazione RTC tramite Tuya Smart…")
    try:
        # Make the RTC request with the same Java API code which the earlier
        # tests already proved works. The P2P SDK used a different endpoint.
        rtc_json = await asyncio.to_thread(events.fetchRtcJson, device_id)
        source = _rtc_dict(json.loads(str(rtc_json)))
        if source is None:
            events.onStatus("Configurazione RTC incompatibile: p2pConfig assente.")
            return
        config = StreamConfig.from_json(source, device_id, local_key)
    except Exception as exc:
        events.onStatus("Configurazione RTC non utilizzabile: " + _type(exc))
        return

    events.onStatus("Configurazione RTC pronta. Apertura segnalazione MQTT…")

    first_frame = asyncio.Event()
    encoded_sample = asyncio.Event()

    def on_frame(frame):
        if not _stopping.is_set():
            if not first_frame.is_set():
                first_frame.set()
                events.onStatus("PRIMO FRAME JPEG RICEVUTO — VIDEO ATTIVO")
            events.onFrame(base64.b64encode(frame).decode("ascii"))

    class VisibleSession(StreamSession):
        def __init__(self, *args):
            super().__init__(*args)
            self.phase = "inizializzazione"
            self.media_records = 0
            self.aes_ok = 0
            self.aes_failed = 0
            self.packets_recognized = 0
            self.video_samples = 0
            self.annexb_candidates = 0
            self._frame_buffer = None
            self._last_codec = None
            self._rtp = RtpVideoBridge()

        def _emit_encoded(self, codec, data):
            if not codec or not data:
                return
            if self._last_codec != codec:
                self._last_codec = codec
                events.onStatus("Dati "+codec.upper()+
                                " identificati: invio al decoder Android…")
            try:
                self.video_samples += 1
                encoded_sample.set()
                events.onEncodedFrame(codec, base64.b64encode(data).decode("ascii"))
            except Exception:
                pass

        def _emit_video(self, data):
            codec,start=_codec_annex_b(data)
            if codec is None:
                return False
            self.annexb_candidates += 1
            # Keep the 00 00 01 Annex B start code; MediaCodec requires it.
            self._emit_encoded(codec,data[start:])
            return True

        def _flush_frame(self):
            if self._frame_buffer:
                self._emit_video(bytes(self._frame_buffer))
            self._frame_buffer = None

        def diagnostics(self):
            return ("Record canale: "+str(self.media_records)+
                    " | AES OK: "+str(self.aes_ok)+
                    " | AES KO: "+str(self.aes_failed)+
                    " | chunk riconosciuti: "+str(self.packets_recognized)+
                    " | RTP: "+str(self._rtp.rtp_count)+
                    " | AnnexB: "+str(self.annexb_candidates)+
                    " | campioni H264/H265: "+str(self.video_samples))

        async def _async_connect_signaling(self, session_id):
            self.phase = "connessione MQTT"
            await super()._async_connect_signaling(session_id)
            events.onStatus("✓ MQTT connesso. Invio richiesta di video…")

        async def _async_publish_offer(self, *args):
            self.phase = "offerta SDP"
            await super()._async_publish_offer(*args)
            events.onStatus("✓ Offerta SDP inviata. Attesa risposta telecamera…")

        async def _async_await_answer(self):
            self.phase = "risposta SDP"
            try:
                answer = await super()._async_await_answer()
            except Exception as exc:
                match=re.search(r"close_reason=(\d+)",str(exc))
                if match:
                    reason=int(match.group(1))
                    if reason==12:
                        events.onStatus("La telecamera ha rifiutato la sessione (codice 12: occupata).")
                    else:
                        events.onStatus("La telecamera ha chiuso la sessione P2P (codice "+str(reason)+").")
                elif "no answer" in str(exc).lower():
                    events.onStatus("Nessuna risposta SDP dalla telecamera entro il timeout.")
                else:
                    events.onStatus("Risposta SDP non accettata dal motore P2P.")
                raise
            events.onStatus("✓ Risposta SDP ricevuta. Apertura relay…")
            return answer

        async def _async_dial_relay(self, *args):
            self.phase = "negoziazione relay"
            relay = await super()._async_dial_relay(*args)
            events.onStatus("✓ Relay P2P negoziato. Avvio canale video…")
            return relay

        def _on_media_record(self, record):
            self.media_records += 1
            if self.media_records == 1:
                events.onStatus("✓ Record media arrivati: analizzo cifratura e codec…")
            try:
                decrypted=decrypt_record(self._answer_key,record)
                self.aes_ok += 1
            except Exception:
                self.aes_failed += 1
                return
            if is_control(decrypted):
                return
            packets=extract_media_packets(decrypted)
            self.packets_recognized += len(packets)
            if packets:
                for packet in packets:
                    if len(packet)<21:
                        continue
                    offset=int.from_bytes(packet[12:16],"big")
                    payload=packet[20:]
                    if offset==0:
                        self._flush_frame()
                        self._frame_buffer=bytearray()
                    if self._frame_buffer is None:
                        continue
                    end=offset+len(payload)
                    if end>2_000_000:
                        self._frame_buffer=None
                        continue
                    if end>len(self._frame_buffer):
                        self._frame_buffer.extend(b"\x00"*(end-len(self._frame_buffer)))
                    self._frame_buffer[offset:end]=payload
            else:
                # Different IPC revisions may not use the MJPEG packet marker.
                if not self._emit_video(decrypted):
                    codec,sample=self._rtp.parse(decrypted)
                    if sample is not None:
                        self._emit_encoded(codec,sample)
            super()._on_media_record(record)

    session = VisibleSession(config, identity, uid, on_frame)
    try:
        try:
            # This is a single attempted session: no rapid reconnect loops which
            # might make the camera refuse further Tuya Smart connections.
            await asyncio.wait_for(session.async_start(), timeout=80.0)
            events.onStatus("Canale media aperto, attendo il primo frame…")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            events.onStatus(
                "Sessione P2P bloccata nella fase: " + session.phase +
                " (" + _type(exc) + ")."
            )
            events.onStatus(session.diagnostics())
            return
        try:
            wait_first = asyncio.create_task(first_frame.wait())
            wait_encoded = asyncio.create_task(encoded_sample.wait())
            wait_stop = asyncio.create_task(_stopping.wait())
            wait_close = asyncio.create_task(session.async_wait_closed())
            done, pending = await asyncio.wait(
                {wait_first, wait_encoded, wait_stop, wait_close},
                timeout=35.0, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if (wait_first in done and first_frame.is_set()) or (
                wait_encoded in done and encoded_sample.is_set()
            ):
                if first_frame.is_set():
                    events.onStatus("JPEG ricevuto. Diretta attiva.")
                else:
                    events.onStatus("Flusso H264/H265 rilevato. Il decoder Android sta tentando di visualizzarlo.")
                remaining = asyncio.create_task(_stopping.wait())
                ended = asyncio.create_task(session.async_wait_closed())
                done, pending = await asyncio.wait(
                    {remaining, ended}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if ended in done:
                    events.onStatus("Sessione video terminata dalla telecamera.")
            elif wait_stop in done and _stopping.is_set():
                events.onStatus("Video interrotto dall'utente.")
            elif wait_close in done:
                events.onStatus("Telecamera ha terminato la sessione senza frame.")
            elif session.media_records:
                session._flush_frame()
                events.onStatus("Nessun JPEG ricostruito. "+session.diagnostics())
                if not session.video_samples:
                    events.onStatus("Formato video non ancora riconosciuto dal decoder.")
                else:
                    events.onStatus("Campioni H264/H265 inviati al decoder Android, "
                                    "ma la visione non è ancora confermata.")
            else:
                events.onStatus(
                    "Canale aperto ma nessun dato video. Telecamera occupata, "
                    "negoziazione incompleta oppure codec incompatibile."
                )
        finally:
            for task in (locals().get("wait_first"),locals().get("wait_encoded"),locals().get("wait_stop"),locals().get("wait_close")):
                if task is not None and not task.done():
                    task.cancel()
    finally:
        session._flush_frame()
        await session.async_close()

def start(sid, ecode, uid, region, install_id, device_id, local_key,
          client_id, composite, ch_key, events):
    global _loop, _stopping
    try:
        asyncio.run(_run(sid, ecode, uid, region, install_id, device_id,
                         local_key, client_id, composite, ch_key, events))
    except Exception as exc:
        events.onStatus("Motore P2P interrotto: " + _type(exc))
    finally:
        _loop = None
        _stopping = None
