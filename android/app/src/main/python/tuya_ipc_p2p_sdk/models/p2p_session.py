"""The server-coordinated P2P session a config fetch mints."""

from __future__ import annotations

from dataclasses import dataclass

from ..json_types import JsonObject, optional_str, require_str


@dataclass(frozen=True, slots=True)
class P2pSession:
    """
    The session the device pre-registers with the signaling server.

    Its ICE credentials and media key have to be offered verbatim: an offer
    carrying the client's own goes unanswered.
    """

    session_id: str
    aes_key: bytes
    ice_ufrag: str
    ice_password: str
    trace_id: str
    uid: str | None

    @classmethod
    def from_json(cls, source: JsonObject) -> P2pSession:
        """Read the session out of a ``p2pConfig`` object."""
        return cls(
            session_id=require_str(source, "sessionId"),
            aes_key=bytes.fromhex(require_str(source, "aesKey")),
            ice_ufrag=require_str(source, "iceUfrag"),
            ice_password=require_str(source, "icePassword"),
            trace_id=optional_str(source, "traceId") or "",
            uid=optional_str(source, "uid"),
        )
