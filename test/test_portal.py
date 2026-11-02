"""The QR token exchange stays automatic and never sends a mobile SID to the portal."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import test_mqtt_identity
from portal import PortalError, PortalSession
from rtc_session import RtcSession
from tuya_ipc_p2p_sdk.signaling.mqtt import MqttClient


class PortalTest(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_uses_exact_mobile_parameter_and_separate_web_session(self):
        portal = PortalSession()
        portal.post = AsyncMock(side_effect=['synthetic-token', {'sid': 'synthetic-web-sid'}])
        gateway = SimpleNamespace(async_call=AsyncMock(side_effect=[[{'gid': 123}], {'ok': True}]))
        account = SimpleNamespace(sid='synthetic-mobile-sid', device_fingerprint='installation')
        async def with_session(call): return await call(account)
        client = SimpleNamespace(_gateway=gateway, _async_with_session=with_session)
        await portal.authenticate(client)
        self.assertEqual(portal.sid, 'synthetic-web-sid')
        auth = gateway.async_call.await_args.args
        self.assertEqual(auth[:3], ('m.life.user.qrcode.login', '1.0',
            {'qrCode': 'synthetic-token', 'homeId': 123, 'terminalId': 'installation'}))
        self.assertIs(auth[3], account)
        self.assertNotIn('synthetic-mobile-sid', str(portal.post.await_args_list))

    async def test_ice_token_keeps_string_urls_while_native_player_gets_lists(self):
        ice = {'urls': 'turn:example.invalid:3478', 'username': 'synthetic', 'credential': 'synthetic'}
        portal = SimpleNamespace(config=AsyncMock(return_value={
            'supportsWebrtc': True, 'motoId': 'synthetic-moto', 'p2pConfig': {'ices': [ice]}}), routes={})
        session = RtcSession(None, 'camera', lambda _: None, portal)
        prepared = await session.prepare()
        self.assertEqual(prepared['iceServers'][0]['urls'], [ice['urls']])
        self.assertEqual(session.ice_servers, [ice])
        self.assertIsInstance(session.ice_servers[0]['urls'], str)

    async def test_expired_web_session_is_recreated_and_config_retried(self):
        portal = PortalSession()
        portal.connect = AsyncMock()
        portal.close = AsyncMock()
        portal.post = AsyncMock(side_effect=[PortalError('USER_SESSION_INVALID'), {'supportsWebrtc': True}])
        portal.sid = 'expired'
        result = await portal.config(None, 'camera', 'session')
        self.assertTrue(result['supportsWebrtc'])
        self.assertEqual(portal.connect.await_count, 2)
        portal.close.assert_awaited_once()
        self.assertEqual(portal.sid, '')

    async def test_mqtt_websocket_reads_fragmented_packets_and_masks_outbound(self):
        client = MqttClient('example.invalid', 443, 'user', 'password', 'client', websocket_path='/mqtt')
        client._reader = asyncio.StreamReader()
        # One MQTT PUBLISH packet split over continuation frames and coalesced with PINGRESP.
        payload = b'abc' * 50
        packet = b'\x30' + bytes([len(payload) | 128, 1]) + payload
        client._reader.feed_data(b'\x02\x02' + packet[:2] + b'\x80\x7e' + (len(packet) - 2).to_bytes(2, 'big') + packet[2:] + b'\x82\x02\xd0\x00')
        self.assertEqual(await client._read_packet(), (0x30, payload))
        self.assertEqual(await client._read_packet(), (0xd0, b''))
        frame = client._websocket_frame(2, payload)
        self.assertEqual(frame[:2], b'\x82\xfe')
        self.assertEqual(int.from_bytes(frame[2:4], 'big'), len(payload))
        mask = frame[4:8]
        self.assertEqual(bytes(x ^ mask[i % 4] for i, x in enumerate(frame[8:])), payload)


if __name__ == '__main__': unittest.main()
