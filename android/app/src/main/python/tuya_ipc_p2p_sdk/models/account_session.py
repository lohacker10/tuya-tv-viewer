"""The logged-in mobile session every session-scoped call derives from."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountSession:
    """
    The credentials the gateway hands back on a successful login.

    ``sid`` scopes the API calls, ``ecode`` keys the encrypted request bodies
    and the signaling MQTT identity, and ``uid`` names the account inside the
    signaling payloads.
    """

    sid: str
    ecode: str
    uid: str
    device_fingerprint: str
