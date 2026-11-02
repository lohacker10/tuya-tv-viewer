"""Thread-safe Android bridge for account login and WebRTC signaling."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from typing import Any

from rtc_session import RtcSession
from portal import PortalSession
from tuya_ipc_p2p_sdk import TuyaDevice, TuyaIpcP2pClient

logging.basicConfig(level=logging.INFO)
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, name="tuya-asyncio", daemon=True).start()
_client: TuyaIpcP2pClient | None = None
_portal: PortalSession | None = None
_cameras: dict[str, TuyaDevice] = {}
_streams: dict[str, RtcSession] = {}
_events: queue.Queue[dict] = queue.Queue(maxsize=1024)


def _run(coroutine: Any, timeout: float = 180) -> Any:
    return asyncio.run_coroutine_threadsafe(coroutine, _loop).result(timeout)


def _emit(event: dict) -> None:
    try:
        _events.put_nowait(event)
    except queue.Full:
        logging.warning("WebRTC event queue is full")


def drain_events() -> str:
    events = []
    while True:
        try:
            events.append(_events.get_nowait())
        except queue.Empty:
            return json.dumps(events)


async def _stop_streams() -> None:
    sessions = list(_streams.values())
    _streams.clear()
    await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
    drain_events()


def stop_streams() -> None:
    _run(_stop_streams())


async def _login(username: str, password: str, country_code: str, region: str, installation_id: str) -> str:
    global _client, _cameras, _portal
    await _stop_streams()
    if _client is not None:
        await _client.async_close()
    _client = TuyaIpcP2pClient(username, password, country_code, region, device_fingerprint=installation_id)
    devices = await _client.async_discover_cameras()
    if _portal is not None: await _portal.close()
    _portal = PortalSession()
    _cameras = {device.device_id: device for device in devices}
    return json.dumps([{"id": d.device_id, "name": d.name, "online": d.online} for d in devices], ensure_ascii=False)


def login(username: str, password: str, country_code: str, region: str, installation_id: str) -> str:
    return _run(_login(username, password, country_code, region, installation_id))


async def _prepare_stream(device_id: str) -> str:
    if _client is None:
        raise RuntimeError("Accedi prima al tuo account Tuya")
    device = _cameras.get(device_id)
    if device is None:
        raise ValueError("Telecamera non presente nell’account")
    previous = _streams.pop(device_id, None)
    if previous is not None:
        await previous.close()
    if len(_streams) >= 4:
        raise ValueError("Sono consentite quattro telecamere contemporanee")
    session = RtcSession(_client, device_id, _emit, _portal)
    try:
        result = await session.prepare()
    except BaseException:
        await session.close()
        raise
    _streams[device_id] = session
    return json.dumps(result)


def prepare_stream(device_id: str) -> str:
    return _run(_prepare_stream(device_id))


async def _rtc_signal(device_id: str, handle: str, kind: str, value: str) -> None:
    session = _streams.get(device_id)
    if session is None or session.handle != handle:
        return
    if kind not in ("offer", "candidate") or not isinstance(value, str) or not 0 < len(value) <= 131072:
        raise ValueError("Segnale WebRTC non valido")
    await session.signal(kind, value)


def rtc_signal(device_id: str, handle: str, kind: str, value: str) -> None:
    _run(_rtc_signal(device_id, handle, kind, value))


async def _logout() -> None:
    global _client, _cameras, _portal
    await _stop_streams()
    if _client is not None:
        await _client.async_close()
    if _portal is not None: await _portal.close()
    _portal = None
    _client = None
    _cameras = {}


def logout() -> None:
    _run(_logout())
