"""Negotiation regression checks, with synthetic data and no broker/camera."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import test_mqtt_identity  # Installs unused JVM cipher stubs for host-side checks.
from rtc_session import RtcSession
from portal import PortalMoto


class RtcSessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_candidates_wait_for_offer_and_answer_stops_retries(self):
        events = []
        session = RtcSession(None, 'synthetic-camera', events.append, None)
        session.config = {'auth': 'synthetic-auth'}
        session.ice_servers = []
        session.moto = SimpleNamespace(
            async_send_webrtc_offer=AsyncMock(), async_send_webrtc_candidate=AsyncMock(),
            async_send_disconnect=AsyncMock(), async_close=AsyncMock())
        await session.signal('candidate', 'candidate:synthetic')
        session.moto.async_send_webrtc_candidate.assert_not_awaited()
        await session.signal('offer', 'synthetic-sdp')
        session.moto.async_send_webrtc_offer.assert_awaited_once_with('synthetic-sdp', [], 'synthetic-auth')
        session.moto.async_send_webrtc_candidate.assert_awaited_once_with('candidate:synthetic')
        session.on_answer('synthetic-answer')
        session.on_answer('duplicate-answer')
        await session.retry_task
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['handle'], session.handle)
        await session.close()
        session.event('error', 'late event')
        self.assertEqual(len(events), 1)

    async def test_offer_requests_h264_secondary_and_candidates_use_webrtc_mode(self):
        mqtt = SimpleNamespace(publish=AsyncMock())
        portal = SimpleNamespace(mqtt=mqtt, msid='synthetic-msid')
        moto = PortalMoto(portal, 'camera', 'session', {'motoId': 'moto', 'protocolVersion': '2.3'}, lambda *_: None)
        await moto.async_send_webrtc_offer('sdp', [{'urls': 'stun:example.invalid'}], 'auth')
        import json
        topic, raw = mqtt.publish.await_args.args
        data = json.loads(raw)
        self.assertEqual(topic, '/av/moto/moto/u/camera')
        self.assertEqual(data['protocol'], 302)
        self.assertEqual(data['pv'], '2.3')
        self.assertEqual(data['data']['msg'], {
            'sdp': 'sdp', 'auth': 'auth', 'mode': 'webrtc', 'datachannel_enable': False,
            'token': [{'urls': 'stun:example.invalid'}], 'stream_type': 1, 'replay': {'is_replay': 0}})
        await moto.async_send_webrtc_candidate('candidate:synthetic')
        self.assertEqual(json.loads(mqtt.publish.await_args.args[1])['data']['msg'], {'candidate': 'a=candidate:synthetic', 'mode': 'webrtc'})
        await moto.async_send_disconnect()
        self.assertEqual(json.loads(mqtt.publish.await_args.args[1])['protocol'], 312)


if __name__ == '__main__':
    unittest.main()
