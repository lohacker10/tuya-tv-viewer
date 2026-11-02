"""Minimal MQTT 3.1.1 client for Tuya's camera signaling channel."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import ssl
from dataclasses import dataclass


@dataclass(frozen=True)
class MqttMessage:
    payload: bytes


def _utf8(value: str) -> bytes:
    encoded = value.encode()
    if len(encoded) > 65535:
        raise ValueError("MQTT string is too long")
    return len(encoded).to_bytes(2, "big") + encoded


def _remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (0x80 if length else 0))
        if not length:
            return bytes(encoded)


class MqttClient:
    """Small QoS 1 subset used for signaling, without a native dependency."""

    def __init__(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str,
        identifier: str,
        keepalive: int = 60,
        tls_context: ssl.SSLContext | None = None,
        clean_session: bool = True,
        websocket_path: str | None = None,
    ) -> None:
        self._websocket_path = websocket_path
        self._websocket_buffer = bytearray()
        self._hostname = hostname
        self._port = port
        self._username = username
        self._password = password
        self._identifier = identifier
        self._keepalive = keepalive
        self._tls_context = tls_context or ssl.create_default_context()
        self._clean_session = clean_session
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._messages: asyncio.Queue[MqttMessage] = asyncio.Queue(maxsize=16)
        self._acks: dict[int, asyncio.Future[bytes]] = {}
        self._packet_id = 0
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> MqttClient:
        self._reader, self._writer = await asyncio.open_connection(
            self._hostname,
            self._port,
            ssl=self._tls_context,
            server_hostname=self._hostname,
        )
        if self._websocket_path is not None:
            await self._upgrade_websocket()
        flags = 0xC0 | (0x02 if self._clean_session else 0)
        connect = (
            _utf8("MQTT")
            + b"\x04"
            + bytes([flags])
            + self._keepalive.to_bytes(2, "big")
            + _utf8(self._identifier)
            + _utf8(self._username)
            + _utf8(self._password)
        )
        await self._send(0x10, connect)
        header, body = await self._read_packet()
        if header >> 4 != 2 or len(body) != 2 or body[1] != 0:
            raise ConnectionError("Tuya signaling broker rejected the MQTT connection")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.async_close()

    async def subscribe(self, topic: str, qos: int = 1) -> None:
        packet_id, waiter = self._new_ack()
        await self._send(0x82, packet_id.to_bytes(2, "big") + _utf8(topic) + bytes([qos]))
        response = await asyncio.wait_for(waiter, 10)
        if len(response) < 3 or response[0:2] != packet_id.to_bytes(2, "big") or response[2] == 0x80:
            raise ConnectionError("Tuya signaling broker rejected the subscription")

    async def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        packet_id, waiter = self._new_ack()
        data = _utf8(topic) + packet_id.to_bytes(2, "big") + payload
        try:
            await self._send(0x32, data)
            await asyncio.wait_for(waiter, 10)
        except Exception:
            self._acks.pop(packet_id, None)
            raise

    async def messages(self):
        while True:
            message = await self._messages.get()
            if message is None: raise ConnectionError("MQTT signaling connection lost")
            yield message

    def start_reader(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop())
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    def _new_ack(self) -> tuple[int, asyncio.Future[bytes]]:
        self._packet_id = self._packet_id % 65535 + 1
        waiter = asyncio.get_running_loop().create_future()
        self._acks[self._packet_id] = waiter
        return self._packet_id, waiter

    async def _send(self, header: int, body: bytes = b"") -> None:
        writer = self._writer
        if writer is None:
            raise ConnectionError("MQTT connection is closed")
        async with self._write_lock:
            data = bytes([header]) + _remaining_length(len(body)) + body
            writer.write(self._websocket_frame(2, data) if self._websocket_path is not None else data)
            await writer.drain()

    async def _read_packet(self) -> tuple[int, bytes]:
        reader = self._reader
        if reader is None:
            raise ConnectionError("MQTT connection is closed")
        header = (await self._read_bytes(1))[0]
        multiplier = 1
        length = 0
        for _ in range(4):
            digit = (await self._read_bytes(1))[0]
            length += (digit & 0x7F) * multiplier
            if digit & 0x80 == 0:
                if length > 1048576:
                    raise ConnectionError("MQTT signaling packet is too large")
                return header, await self._read_bytes(length)
            multiplier *= 128
        raise ConnectionError("Invalid MQTT packet length")

    async def _upgrade_websocket(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET {self._websocket_path} HTTP/1.1\r\nHost: {self._hostname}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: mqtt\r\n"
            "Origin: https://protect-eu.ismartlife.me\r\n\r\n"
        )
        self._writer.write(request.encode())
        await self._writer.drain()
        response = (await self._reader.readuntil(b"\r\n\r\n")).decode("ascii")
        lines = response.split("\r\n")
        headers = {name.lower(): value.strip() for line in lines[1:] if ":" in line for name, value in [line.split(":", 1)]}
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if (not lines[0].startswith("HTTP/1.1 101 ") or
                headers.get("sec-websocket-accept", "").strip() != accept or
                headers.get("sec-websocket-protocol", "").strip() != "mqtt"):
            raise ConnectionError("Tuya WebSocket upgrade rejected")

    @staticmethod
    def _websocket_frame(opcode: int, data: bytes) -> bytes:
        length = len(data)
        header = bytes([0x80 | opcode])
        if length < 126: header += bytes([0x80 | length])
        elif length <= 65535: header += bytes([0xfe]) + length.to_bytes(2, "big")
        else: header += bytes([0xff]) + length.to_bytes(8, "big")
        mask = secrets.token_bytes(4)
        return header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(data))

    async def _read_bytes(self, length: int) -> bytes:
        if self._websocket_path is None:
            return await self._reader.readexactly(length)
        while len(self._websocket_buffer) < length:
            first, second = await self._reader.readexactly(2)
            opcode, size = first & 15, second & 127
            if second & 128 or first & 0x70:
                raise ConnectionError("Unsupported WebSocket frame")
            if size == 126: size = int.from_bytes(await self._reader.readexactly(2), "big")
            elif size == 127: size = int.from_bytes(await self._reader.readexactly(8), "big")
            if size > 1048576 or (opcode >= 8 and (size > 125 or not first & 128)):
                raise ConnectionError("Invalid WebSocket frame length")
            data = await self._reader.readexactly(size)
            if opcode in (0, 2): self._websocket_buffer.extend(data)
            elif opcode == 9:
                async with self._write_lock:
                    self._writer.write(self._websocket_frame(10, data))
                    await self._writer.drain()
            elif opcode == 8: raise ConnectionError("Tuya WebSocket closed")
            elif opcode != 10: raise ConnectionError("Unsupported WebSocket opcode")
        data = bytes(self._websocket_buffer[:length])
        del self._websocket_buffer[:length]
        return data

    async def _read_loop(self) -> None:
        try:
            while True:
                header, body = await self._read_packet()
                packet_type = header >> 4
                if packet_type == 3:
                    await self._consume_publish(header, body)
                elif packet_type in (4, 9):
                    if len(body) >= 2:
                        packet_id = int.from_bytes(body[:2], "big")
                        waiter = self._acks.pop(packet_id, None)
                        if waiter is not None and not waiter.done():
                            waiter.set_result(body)
                elif packet_type == 12:
                    await self._send(0xD0)
        except asyncio.CancelledError:
            raise
        except Exception as exception:
            for waiter in self._acks.values():
                if not waiter.done():
                    waiter.set_exception(ConnectionError(str(exception)))
            self._acks.clear()
            if self._messages.full(): self._messages.get_nowait()
            self._messages.put_nowait(None)

    async def _consume_publish(self, header: int, body: bytes) -> None:
        if len(body) < 2:
            return
        topic_length = int.from_bytes(body[:2], "big")
        offset = 2 + topic_length
        qos = (header >> 1) & 0x03
        if offset > len(body):
            return
        if qos:
            if len(body) < offset + 2:
                return
            packet_id = body[offset : offset + 2]
            offset += 2
            if qos == 1:
                await self._send(0x40, packet_id)
        payload = body[offset:]
        if self._messages.full():
            self._messages.get_nowait()
        self._messages.put_nowait(MqttMessage(payload))

    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._keepalive // 2)
                await self._send(0xC0)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def async_close(self) -> None:
        for task in (self._keepalive_task, self._reader_task):
            if task is not None:
                task.cancel()
        for task in (self._keepalive_task, self._reader_task):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._keepalive_task = None
        self._reader_task = None
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            try:
                packet = b"\xe0\x00"
                writer.write(self._websocket_frame(2, packet) if self._websocket_path is not None else packet)
                await writer.drain()
            except OSError:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
