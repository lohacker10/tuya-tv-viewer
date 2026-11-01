"""
The ``et=3`` encrypted request and response body.

AES-GCM with a fresh 12-byte nonce, on the wire as base64 of
``nonce || ciphertext || tag``. Despite the Java helper being named
"appendNonce", the nonce goes at the front.
"""

from __future__ import annotations

import secrets
import gzip
from base64 import b64decode, b64encode

from java import jarray, jbyte
from javax.crypto import Cipher
from javax.crypto.spec import GCMParameterSpec, SecretKeySpec

from ..exceptions import TuyaIpcP2pProtocolError

_NONCE_LENGTH = 12
_TAG_LENGTH = 16


def encrypt_post_data(key: str, post_json: bytes) -> str:
    """Encrypt one request body and return it base64-encoded."""
    nonce = secrets.token_bytes(_NONCE_LENGTH)
    cipher = Cipher.getInstance("AES/GCM/NoPadding")
    cipher.init(
        Cipher.ENCRYPT_MODE,
        SecretKeySpec(jarray(jbyte)(key.encode()), "AES"),
        GCMParameterSpec(_TAG_LENGTH * 8, jarray(jbyte)(nonce)),
    )
    sealed = bytes(cipher.doFinal(jarray(jbyte)(post_json)))
    return b64encode(nonce + sealed).decode()


def decrypt_post_data(key: str, encrypted: str) -> bytes:
    """Decrypt one base64 body, whether it came from a request or a response."""
    try:
        raw = b64decode(encrypted, validate=True)
    except ValueError as exception:
        raise TuyaIpcP2pProtocolError(f"Failed to decode body: {exception}") from exception
    if len(raw) < _NONCE_LENGTH + _TAG_LENGTH:
        raise TuyaIpcP2pProtocolError("Failed to decode body: shorter than nonce and tag")
    try:
        cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            SecretKeySpec(jarray(jbyte)(key.encode()), "AES"),
            GCMParameterSpec(_TAG_LENGTH * 8, jarray(jbyte)(raw[:_NONCE_LENGTH])),
        )
        plaintext = bytes(cipher.doFinal(jarray(jbyte)(raw[_NONCE_LENGTH:])))
        return gzip.decompress(plaintext) if plaintext.startswith(b"\x1f\x8b") else plaintext
    except Exception as exception:
        raise TuyaIpcP2pProtocolError("Failed to decrypt body: authentication tag") from exception
