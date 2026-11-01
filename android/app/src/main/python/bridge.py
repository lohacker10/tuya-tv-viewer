"""Small thread-safe bridge between Android and the reverse-engineered client."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any

from tuya_ipc_p2p_sdk import TuyaDevice, TuyaIpcP2pClient

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, name="tuya-asyncio", daemon=True)
_thread.start()
_frames: dict[str, bytes] = {}
_frames_lock = threading.Lock()
_client: TuyaIpcP2pClient | None = None
_cameras: dict[str, TuyaDevice] = {}
_streams: dict[str, Any] = {}
_stream_started_at: dict[str, float] = {}
_pumps: list[asyncio.Task[None]] = []


def _run(coroutine: Any, timeout: float = 180) -> Any:
    return asyncio.run_coroutine_threadsafe(coroutine, _loop).result(timeout)


async def _stop_streams() -> None:
    global _pumps
    for task in _pumps:
        task.cancel()
    for task in _pumps:
        try:
            await task
        except asyncio.CancelledError:
            pass
    _pumps = []
    for stream in _streams.values():
        await stream.async_stop()
    _streams.clear()
    _stream_started_at.clear()
    with _frames_lock:
        _frames.clear()


async def _pump(device_id: str, stream: Any) -> None:
    async for frame in stream.async_frames():
        with _frames_lock:
            _frames[device_id] = frame


async def _login(username: str, password: str, country_code: str, region: str) -> str:
    global _client, _cameras
    await _stop_streams()
    if _client is not None:
        await _client.async_close()
    _client = TuyaIpcP2pClient(username, password, country_code, region)
    devices = await _client.async_discover_cameras()
    _cameras = {device.device_id: device for device in devices}
    return json.dumps(
        [
            {"id": device.device_id, "name": device.name, "online": device.online}
            for device in devices
        ],
        ensure_ascii=False,
    )


def login(username: str, password: str, country_code: str, region: str) -> str:
    return _run(_login(username, password, country_code, region))


async def _start_streams(device_ids: list[str]) -> None:
    await _stop_streams()
    client = _client
    if client is None:
        raise RuntimeError("Accedi prima al tuo account Tuya")
    # shortcut: one video client per camera; use official video support if multi-client streaming is needed.
    for device_id in device_ids[:4]:
        device = _cameras.get(device_id)
        if device is None:
            continue
        stream = client.create_camera_stream(device.device_id, device.local_key)
        _streams[device_id] = stream
        _stream_started_at[device_id] = time.monotonic()
        await stream.async_start()
        _pumps.append(asyncio.create_task(_pump(device_id, stream)))


def start_streams(device_ids_json: str) -> None:
    device_ids = json.loads(device_ids_json)
    if not isinstance(device_ids, list) or any(not isinstance(item, str) for item in device_ids):
        raise ValueError("Elenco telecamere non valido")
    _run(_start_streams(device_ids))


def drain_frames() -> dict[str, bytes]:
    with _frames_lock:
        frames = dict(_frames)
        _frames.clear()
    return frames


async def _stream_statuses() -> dict[str, str]:
    now = time.monotonic()
    statuses = {}
    for device_id, stream in _streams.items():
        if stream.streaming:
            status = "In diretta"
        elif stream.needs_power_cycle:
            status = "P2P rifiutato ripetutamente; chiudi altri viewer e riavvia la telecamera"
        elif stream.last_error:
            status = f"Errore P2P: {stream.last_error}"
        elif now - _stream_started_at.get(device_id, now) >= 45:
            status = "Nessun frame dopo 45 secondi"
        else:
            status = "Connessione P2P…"
        statuses[device_id] = status
    return statuses


def stream_statuses() -> dict[str, str]:
    return _run(_stream_statuses())


async def _logout() -> None:
    global _client, _cameras
    await _stop_streams()
    if _client is not None:
        await _client.async_close()
    _client = None
    _cameras = {}


def logout() -> None:
    _run(_logout())
