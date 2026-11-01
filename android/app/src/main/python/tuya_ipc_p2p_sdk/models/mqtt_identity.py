"""The signaling MQTT identity derived from a login session."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MqttIdentity:
    """Everything needed to connect the regional signaling broker as this account."""

    host: str
    port: int
    client_id: str
    username: str
    password: str
