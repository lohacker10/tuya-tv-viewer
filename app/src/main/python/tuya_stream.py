"""Tuya Smart native P2P video proof-of-concept. No server.

Uses MIT-licensed roquerodrigo/tuya-ipc-p2p-sdk 0.1.1, installed from a
pinned upstream wheel at build time. It is only verified on MJPEG cameras.
Session credentials are passed from the Android app in memory, never logged.
"""
import asyncio
import base64
import hashlib
import logging
import time

_loop = None
_stopping = None

def stop():
    global _loop, _stopping
    if _loop is not None and _stopping is not None:
        _loop.call_soon_threadsafe(_stopping.set)

def _category(exc):
    return type(exc).__name__[:55]

async def _run(sid, ecode, uid, region, install_id, device_id, local_key,
               client_id, composite, ch_key, events):
    global _loop, _stopping
    _loop = asyncio.get_running_loop()
    _stopping = asyncio.Event()
    logging.getLogger("tuya_ipc_p2p_sdk").setLevel(logging.CRITICAL)

    from tuya_ipc_p2p_sdk import AccountSession, MqttIdentity, TuyaIpcP2pClient
    import tuya_ipc_p2p_sdk.gateway.client as gw

    # The upstream SDK assumes Smart Life: we adapt its request identity
    # to the already-authenticated Tuya Smart account, without logging in twice.
    gw.CLIENT_ID = client_id
    gw.CH_KEY = ch_key
    gw.APP_VERSION = "7.8.6"
    gw.SDK_VERSION = "5.24.0"
    gw.TTID = "international"

    tail = hashlib.md5(
        (hashlib.md5(client_id.encode()).hexdigest() + ecode).encode()
    ).hexdigest()[-16:]
    mqtt_username = "p1000018_v1_%s_%s_mb_%s%s" % (client_id, ch_key, sid, tail)
    mqtt_password = hashlib.md5(
        (hashlib.md5(composite.encode()).hexdigest() + ecode).encode()
    ).hexdigest()[8:24]
    mqtt_client_id = "com.tuya.smart_mb_%s_%s_DEFAULT" % (
        install_id,
        hashlib.md5((uid + "sdkfasodifca").encode()).hexdigest()
    )
    identity = MqttIdentity(
        "m1-" + region + ".lifeaiot.com",
        8883, mqtt_client_id, mqtt_username, mqtt_password
    )

    events.onStatus("Connessione P2P in corso. Avvio la sessione video della telecamera…")
    async with TuyaIpcP2pClient("", "", "39", region=region,
                               device_fingerprint=install_id) as sdk:
        sdk._account = AccountSession(sid, ecode, uid, install_id)
        sdk._gateway._composite_key = composite
        sdk._gateway.mqtt_identity = lambda session: identity
        stream = sdk.create_camera_stream(
            device_id, local_key,
            retry_min_seconds=12.0, retry_max_seconds=30.0,
            busy_refusal_limit=2, refused_retry_seconds=900.0,
        )
        try:
            await stream.async_start()
            events.onStatus("Motore P2P avviato; attendo un frame JPEG (max 50 secondi)…")
            first = await stream.async_wait_for_frame(50.0)
            if _stopping.is_set():
                return
            if not first:
                events.onStatus(
                    "Nessun frame JPEG ricevuto. Possibile codec H.264, sessione "
                    "non supportata oppure telecamera occupata in Tuya Smart."
                )
                return
            events.onStatus("PRIMO FRAME RICEVUTO. Diretta attiva.")
            async def consume():
                last = 0.0
                async for frame in stream.async_frames():
                    if _stopping.is_set():
                        return
                    now = time.monotonic()
                    if now - last >= 0.25:
                        last = now
                        events.onFrame(base64.b64encode(frame).decode("ascii"))
            frames = asyncio.create_task(consume())
            stopper = asyncio.create_task(_stopping.wait())
            finished, pending = await asyncio.wait(
                {frames, stopper}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in finished:
                if task is frames and not task.cancelled() and task.exception():
                    events.onStatus("Errore decodifica video: " + _category(task.exception()))
        finally:
            await stream.async_stop()

def start(sid, ecode, uid, region, install_id, device_id, local_key,
          client_id, composite, ch_key, events):
    global _loop, _stopping
    try:
        asyncio.run(_run(sid, ecode, uid, region, install_id, device_id, local_key,
                         client_id, composite, ch_key, events))
    except Exception as exc:
        events.onStatus(
            "Tentativo di video non riuscito: " + _category(exc) +
            ". Il protocollo P2P o il codec della telecamera potrebbe essere incompatibile."
        )
    finally:
        _loop = None
        _stopping = None
