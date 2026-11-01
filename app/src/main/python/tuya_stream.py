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

_loop = None
_stopping = None

def stop():
    global _loop, _stopping
    if _loop is not None and _stopping is not None:
        _loop.call_soon_threadsafe(_stopping.set)

def _type(exc):
    return type(exc).__name__[:65]

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
            answer = await super()._async_await_answer()
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
                events.onStatus("✓ Pacchetti video ricevuti: attendo frame JPEG…")
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
            return
        try:
            wait_first = asyncio.create_task(first_frame.wait())
            wait_stop = asyncio.create_task(_stopping.wait())
            wait_close = asyncio.create_task(session.async_wait_closed())
            done, pending = await asyncio.wait(
                {wait_first, wait_stop, wait_close},
                timeout=35.0, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if wait_first in done and first_frame.is_set():
                events.onStatus("Diretta video avviata. Premi FERMA VIDEO per chiuderla.")
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
                events.onStatus(
                    "Ricevuti " + str(session.media_records) +
                    " pacchetti media, ma nessun JPEG. Codec o formato non supportato."
                )
            else:
                events.onStatus(
                    "Canale aperto ma nessun dato video. Telecamera occupata, "
                    "negoziazione incompleta oppure codec incompatibile."
                )
        finally:
            for task in (locals().get("wait_first"),locals().get("wait_stop"),locals().get("wait_close")):
                if task is not None and not task.done():
                    task.cancel()
    finally:
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
