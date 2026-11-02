"""Tuya portal signaling for a native WebRTC receiver."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import json
from collections.abc import Callable
from uuid import uuid4

from tuya_ipc_p2p_sdk import TuyaIpcP2pClient
from portal import PortalMoto


class RtcSession:
    def __init__(self, client: TuyaIpcP2pClient, device_id: str, emit: Callable[[dict], None], portal, quality="sd"):
        if quality not in ("sd", "hd"): raise ValueError("Qualità video non valida")
        self.quality = quality
        self.portal = portal
        self.client = client
        self.device_id = device_id
        self.emit = emit
        self.handle = uuid4().hex
        self.config = None
        self.moto = None
        self.offer = None
        self.candidates: list[str] = []
        self.answered = asyncio.Event()
        self.retry_task = None
        self.closed = False
        self.offer_sent = False
        self.hevc = False

    def event(self, kind: str, value: str) -> None:
        if not self.closed:
            self.emit({"id": self.device_id, "handle": self.handle, "type": kind, "value": value})

    def on_answer(self, sdp: str) -> None:
        if not self.answered.is_set():
            logging.info("RTC WebRTC answer received")
            self.answered.set()
            self.event("answer", sdp)

    async def prepare(self) -> dict:
        self.config = await self.portal.config(self.client, self.device_id, self.handle)
        if self.config.get('supportsWebrtc') is not True:
            raise RuntimeError("La telecamera non dichiara supporto WebRTC")
        self.moto = PortalMoto(self.portal, self.device_id, self.handle, self.config,
            lambda kind, value: self.on_answer(value) if kind == 'answer' else self.event(kind, value))
        self.portal.routes[self.handle] = self.moto
        logging.info("RTC signaling connected")
        servers = []
        for server in self.config.get('p2pConfig', {}).get('ices', []):
            if not isinstance(server, dict): continue
            urls = server.get("urls", server.get("url"))
            urls = [urls] if isinstance(urls, str) else urls
            if not isinstance(urls, list):
                continue
            urls = [url for url in urls if isinstance(url, str) and url.startswith(("stun:", "turn:", "turns:"))]
            if urls:
                item = {"urls": urls}
                for key in ("username", "credential"):
                    if isinstance(server.get(key), str):
                        item[key] = server[key]
                servers.append(item)
        if not servers:
            raise RuntimeError("Tuya non ha fornito server ICE validi")
        self.ice_servers = [server for server in self.config.get('p2pConfig', {}).get('ices', [])
                            if isinstance(server, dict) and isinstance(server.get('urls'), str)
                            and server['urls'].startswith(('stun:', 'turn:', 'turns:'))]
        skill = self.config.get('skill', {})
        if isinstance(skill, str):
            try: skill = json.loads(skill)
            except ValueError: skill = {}
        videos = skill.get('videos', []) if isinstance(skill, dict) else []
        video = next((item for item in videos if isinstance(item, dict) and item.get('streamType') == (2 if self.quality == 'hd' else 4)), {})
        self.hevc = self.quality == 'hd' and video.get('codecType') == 4
        logging.info('RTC profile=%s codec=%s size=%sx%s', self.quality, video.get('codecType'), video.get('width'), video.get('height'))
        return {"handle": self.handle, "iceServers": servers, "codec": video.get('codecType'), "hevc": self.hevc}

    async def signal(self, kind: str, value: str) -> None:
        if self.closed:
            return
        if kind == "candidate":
            if len(self.candidates) >= 128:
                raise ValueError("Troppi candidati ICE")
            self.candidates.append(value)
            if self.offer_sent:
                await self.moto.async_send_webrtc_candidate(value)
        elif kind == "resolution":
            expected = "0" if self.quality == "hd" else "1"
            if value != expected or self.hevc:
                raise ValueError("Cambio risoluzione non valido per questa sessione")
            await self.moto.send("resolution", {"mode": "webrtc", "cmdValue": int(value)}, protocol=312)
        elif kind == "offer":
            if self.offer is not None:
                if self.offer != value:
                    raise ValueError("Offerta già inviata per questa sessione")
                return
            self.offer = value
            await self.send_offer()
            logging.info("RTC WebRTC offer sent")
            self.offer_sent = True
            for candidate in self.candidates:
                await self.moto.async_send_webrtc_candidate(candidate)
            self.retry_task = asyncio.create_task(self.retry_offer())
        else:
            raise ValueError("Segnale WebRTC non valido")

    async def send_offer(self) -> None:
        await self.moto.async_send_webrtc_offer(
            self.offer, self.ice_servers, self.config.get('auth'),
            stream_type=0 if self.quality == 'hd' else 1, datachannel_enable=self.hevc
        )

    async def retry_offer(self) -> None:
        try:
            for _ in range(5):
                try:
                    await asyncio.wait_for(self.answered.wait(), 3)
                    return
                except TimeoutError:
                    await self.send_offer()
                    for candidate in self.candidates:
                        await self.moto.async_send_webrtc_candidate(candidate)
            if not self.answered.is_set():
                self.event("error", "La telecamera non risponde all’offerta WebRTC")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.event("error", f"Segnalazione WebRTC interrotta ({type(error).__name__})")

    async def close(self) -> None:
        self.closed = True
        if self.retry_task is not None:
            self.retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.retry_task
        if self.moto is not None:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(2):
                    await self.moto.async_send_disconnect()
            with contextlib.suppress(Exception):
                async with asyncio.timeout(3):
                    await self.moto.async_close()
