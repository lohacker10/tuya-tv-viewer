"""
The controlled-role ICE agent.

The device runs its connectivity checks as the *controlling* agent even though
the client is the offerer, and it waits for that negotiation to conclude before
it commits media to the relay. A client that also claims the controlling role
produces a role conflict the device never resolves: it opens the video
conversation, sends the first frames, and tears the session down with
``close_reason=6`` seconds later.

So this agent takes the controlled role: it binds a socket, publishes its host
candidate and answers the device's binding requests. It never sends checks of
its own. Media rides the relay, so no candidate pair has to be nominated for
video to flow.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from typing import TYPE_CHECKING
from zlib import crc32

from ..const import LOGGER
from ..crypto import hmac_sha1

if TYPE_CHECKING:
    from collections.abc import Callable

_STUN_MAGIC_COOKIE = 0x2112A442
_BINDING_REQUEST = 0x0001
_BINDING_SUCCESS = 0x0101

_ATTRIBUTE_XOR_MAPPED_ADDRESS = 0x0020
_ATTRIBUTE_MESSAGE_INTEGRITY = 0x0008
_ATTRIBUTE_FINGERPRINT = 0x8028

_FINGERPRINT_XOR = 0x5354554E
_HOST_CANDIDATE_PRIORITY = 2130706431
_STUN_HEADER_LENGTH = 20
_INTEGRITY_LENGTH = 24
_FINGERPRINT_LENGTH = 8


def local_address() -> str:
    """
    Return the IPv4 address the default route leaves from.

    A UDP socket that is connected but never written to picks the interface the
    kernel would route through without sending a packet — which is the address
    a camera on the same network reaches this host on.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()
    return str(address)


def candidate_line(address: str, port: int) -> str:
    """Build the trickled host candidate for an address and port."""
    foundation = crc32(address.encode())
    return (
        f"a=candidate:{foundation} 1 udp {_HOST_CANDIDATE_PRIORITY} {address} {port} typ host\r\n"
    )


def _attribute(attribute_type: int, value: bytes) -> bytes:
    """Build one STUN attribute, padded to a four-byte boundary."""
    padding = (4 - (len(value) % 4)) % 4
    return (
        attribute_type.to_bytes(2, "big")
        + len(value).to_bytes(2, "big")
        + value
        + b"\x00" * padding
    )


def _xor_mapped_address(address: str, port: int) -> bytes:
    """Build the XOR-MAPPED-ADDRESS value of an IPv4 endpoint."""
    try:
        raw = socket.inet_aton(address)
    except OSError:
        raw = b"\x00\x00\x00\x00"
    xored = (int.from_bytes(raw, "big") ^ _STUN_MAGIC_COOKIE).to_bytes(4, "big")
    return b"\x00\x01" + (port ^ (_STUN_MAGIC_COOKIE >> 16)).to_bytes(2, "big") + xored


def build_binding_success(
    transaction_id: bytes, address: str, port: int, local_password: str
) -> bytes:
    """
    Assemble a binding success response.

    MESSAGE-INTEGRITY and FINGERPRINT are each computed over the message with
    its length field already extended to cover that attribute but not what
    follows it.
    """
    body = _attribute(_ATTRIBUTE_XOR_MAPPED_ADDRESS, _xor_mapped_address(address, port))
    header = (
        _BINDING_SUCCESS.to_bytes(2, "big")
        + b"\x00\x00"
        + _STUN_MAGIC_COOKIE.to_bytes(4, "big")
        + transaction_id
    )
    message = bytearray(header + body)
    message[2:4] = (len(body) + _INTEGRITY_LENGTH).to_bytes(2, "big")
    integrity = hmac_sha1(local_password.encode(), bytes(message))
    message += _attribute(_ATTRIBUTE_MESSAGE_INTEGRITY, integrity)

    message[2:4] = (len(message) - _STUN_HEADER_LENGTH + _FINGERPRINT_LENGTH).to_bytes(2, "big")
    fingerprint = (crc32(bytes(message)) ^ _FINGERPRINT_XOR) & 0xFFFFFFFF
    return bytes(message) + _attribute(_ATTRIBUTE_FINGERPRINT, fingerprint.to_bytes(4, "big"))


class IceResponder(asyncio.DatagramProtocol):
    """Binds a UDP socket, publishes its host candidate and answers binding requests."""

    def __init__(self, local_password: str, on_candidate: Callable[[str], None]) -> None:
        """Bind the responder to the session's local ICE password."""
        self._local_password = local_password
        self._on_candidate = on_candidate
        self._transport: asyncio.DatagramTransport | None = None

    async def async_gather(self) -> None:
        """Bind the socket and publish the host candidate it listens on."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=("0.0.0.0", 0),  # noqa: S104
        )
        self._transport = transport
        port = transport.get_extra_info("sockname")[1]
        self._on_candidate(candidate_line(local_address(), int(port)))

    def datagram_received(self, data: bytes, addr: tuple[str | bytes, int]) -> None:
        """Answer one binding request; anything else is ignored."""
        transport = self._transport
        if transport is None or len(data) < _STUN_HEADER_LENGTH:
            return
        if int.from_bytes(data[0:2], "big") != _BINDING_REQUEST:
            return
        if int.from_bytes(data[4:8], "big") != _STUN_MAGIC_COOKIE:
            return
        host, port = addr[0], addr[1]
        address = host.decode() if isinstance(host, bytes) else host
        LOGGER.debug("Answered an ICE binding request from %s:%s", address, port)
        transport.sendto(
            build_binding_success(data[8:20], address, int(port), self._local_password), addr
        )

    def error_received(self, exc: Exception) -> None:
        """Log a socket error rather than letting it end the session."""
        LOGGER.debug("ICE socket error: %s", exc)

    def close(self) -> None:
        """Release the socket."""
        transport = self._transport
        self._transport = None
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()
