"""Regression checks for concurrent camera connections, without network access."""

import asyncio
from pathlib import Path
import sys
from types import ModuleType
import unittest


def unused_jvm_crypto(*args, **kwargs):
    raise AssertionError("This check must not invoke Android cryptography")


# Account identity hashing is standard Python; JVM ciphers are unused here.
for name, members in {
    "java": ("jarray", "jbyte"),
    "java.math": ("BigInteger",),
    "java.security": ("KeyFactory",),
    "java.security.spec": ("RSAPublicKeySpec",),
    "javax": (),
    "javax.crypto": ("Cipher",),
    "javax.crypto.spec": ("IvParameterSpec", "SecretKeySpec", "GCMParameterSpec"),
}.items():
    module = ModuleType(name)
    module.__path__ = []
    for member in members:
        setattr(module, member, unused_jvm_crypto)
    sys.modules[name] = module

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "android/app/src/main/python"))
from tuya_ipc_p2p_sdk import TuyaIpcP2pClient
from tuya_ipc_p2p_sdk.models import AccountSession


class MqttIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def test_four_camera_sockets_have_stable_distinct_ids(self):
        client = TuyaIpcP2pClient("unused", "unused", "39", "eu")
        account = AccountSession("synthetic-session", "synthetic-ecode", "synthetic-user", "a" * 44)
        client._account = account
        base = await client.async_mqtt_identity()
        identities = await asyncio.gather(*(client.async_mqtt_identity(f"camera-{i}") for i in range(4)))
        self.assertEqual(len({item.client_id for item in identities}), 4)
        self.assertEqual(identities[0], await client.async_mqtt_identity("camera-0"))
        self.assertTrue(all(item.username == base.username and item.password == base.password for item in identities))
        self.assertEqual(client._account, account)

    async def test_different_installations_do_not_disconnect_each_other(self):
        clients = [TuyaIpcP2pClient("unused", "unused", "39", "eu") for _ in range(2)]
        for index, client in enumerate(clients):
            client._account = AccountSession("synthetic-session", "synthetic-ecode", "synthetic-user", str(index) * 44)
        identities = [await client.async_mqtt_identity("camera-0") for client in clients]
        self.assertNotEqual(identities[0].client_id, identities[1].client_id)


if __name__ == "__main__":
    unittest.main()
