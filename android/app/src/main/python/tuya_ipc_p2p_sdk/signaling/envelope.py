"""
The binary envelope every signaling MQTT payload rides in.

``"2.2" | crc32(seq‖src‖body) BE | seq BE | src[4] | body``, where the CRC
covers everything after the CRC field and ``body`` is the AES-128-ECB
ciphertext of the JSON, keyed by the device local key.
"""

from __future__ import annotations

from typing import NamedTuple
from zlib import crc32

from ..crypto import aes_ecb_decrypt, aes_ecb_encrypt
from ..exceptions import TuyaIpcP2pProtocolError
from ..json_types import JsonObject, JsonValue, dump_json, parse_json_object

_VERSION = b"2.2"
_HEADER_LENGTH = 15
_SOURCE_LENGTH = 4

SIG_QUERY_PROTOCOL = 22
SESSION_PROTOCOL = 302


class DecodedFrame(NamedTuple):
    """One decoded envelope, before its body is decrypted."""

    sequence: int
    source: bytes
    body: bytes


def encode_frame(sequence: int, source: bytes, body: bytes) -> bytes:
    """Wrap an already-encrypted body in the envelope."""
    tail = sequence.to_bytes(4, "big") + source[:_SOURCE_LENGTH] + body
    return _VERSION + crc32(tail).to_bytes(4, "big") + tail


def decode_frame(payload: bytes) -> DecodedFrame:
    """Verify the envelope's CRC and split it."""
    if len(payload) < _HEADER_LENGTH or payload[:3] != _VERSION:
        raise TuyaIpcP2pProtocolError("Failed to decode envelope: not a 2.2 frame")
    want = int.from_bytes(payload[3:7], "big")
    got = crc32(payload[7:])
    if got != want:
        raise TuyaIpcP2pProtocolError(
            f"Failed to decode envelope: crc32 {got:08x}, want {want:08x}"
        )
    return DecodedFrame(
        sequence=int.from_bytes(payload[7:11], "big"),
        source=payload[11:_HEADER_LENGTH],
        body=payload[_HEADER_LENGTH:],
    )


def encode_payload(
    key: bytes,
    sequence: int,
    source: bytes,
    data: JsonValue,
    epoch_seconds: int,
    protocol: int,
) -> bytes:
    """Serialize, ECB-encrypt and frame one signaling payload."""
    plain = dump_json({"data": data, "protocol": protocol, "t": epoch_seconds})
    return encode_frame(sequence, source, aes_ecb_encrypt(key, plain))


def decode_payload(key: bytes, payload: bytes) -> JsonObject:
    """Return the ``data`` object of one inbound signaling payload."""
    decoded = parse_json_object(aes_ecb_decrypt(key, decode_frame(payload).body))
    data = decoded.get("data")
    if not isinstance(data, dict):
        raise TuyaIpcP2pProtocolError("Failed to decode payload: no data object")
    return data
