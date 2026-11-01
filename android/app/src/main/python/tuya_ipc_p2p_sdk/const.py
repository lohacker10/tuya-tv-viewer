"""Client and region constants of the Tuya mobile app build this SDK impersonates."""

from __future__ import annotations

import hashlib
import hmac
from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

PACKAGE_NAME = "com.tuya.smart"
CERT_SHA256 = "93:21:9F:C2:73:E2:20:0F:4A:DE:E5:F7:19:1D:C6:56:BA:2A:2D:7B:2F:F5:D2:4C:D5:5C:4B:61:55:00:1E:40"
DERIVED_KEY = "f3hd7pet4p83kemjdf5wqsa5tavrv579"
APP_SECRET = "5gdtanjtf38vyxkqh87cjwfcqjhvjjqa"  # noqa: S105

COMPOSITE_KEY = f"{PACKAGE_NAME}_{CERT_SHA256}_{DERIVED_KEY}_{APP_SECRET}"

CLIENT_ID = "3cxxt3au9x33ytvq3h9j"
CH_KEY = hmac.new(
    CLIENT_ID.encode(), f"{PACKAGE_NAME}_{CERT_SHA256}".encode(), hashlib.sha256
).hexdigest()[8:16]
APP_VERSION = "7.8.6"
SDK_VERSION = "5.24.0"
DEVICE_CORE_VERSION = "5.17.0"
LANGUAGE = "en"
TTID = "international"

PARTNER_IDENTITY = "p1000018"
CLIENT_ID_SALT = "sdkfasodifca"

# The install id identifies this client to the account. Any stable 44-character
# value works, but it must not change between logins of the same account.
DEFAULT_DEVICE_FINGERPRINT = "a" * 44

DEFAULT_REGION = "us"
REGIONS: tuple[str, ...] = ("eu", "us", "cn", "in", "sg")

# The device's own reason for turning an offer down: a previous session is
# still held. See PROTOCOL.md for the values seen in practice.
CLOSE_REASON_BUSY = 12


def gateway_url(region: str = DEFAULT_REGION) -> str:
    """Return the mobile API gateway of a region."""
    hosts = {
        "eu": "a1.tuyaeu.com",
        "us": "a1.tuyaus.com",
        "cn": "a1.tuyacn.com",
        "in": "a1.tuyain.com",
        "sg": "a1-sg.iotbing.com",
    }
    try:
        return f"https://{hosts[region]}/api.json"
    except KeyError as exception:
        raise ValueError(f"Unsupported Tuya region: {region}") from exception


def broker_host(region: str = DEFAULT_REGION) -> str:
    """Return the signaling MQTT broker host of a region."""
    return f"m1-{region}.lifeaiot.com"


BROKER_PORT = 8883
