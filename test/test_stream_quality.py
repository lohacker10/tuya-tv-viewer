"""Select the main codec in fullscreen while retaining compatible SD previews."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
import test_mqtt_identity
from rtc_session import RtcSession


class StreamQualityTest(unittest.IsolatedAsyncioTestCase):
    async def test_preview_and_fullscreen_choose_the_right_stream_and_transport(self):
        for quality, codec, stream_type, hevc in [('sd', 4, 1, False), ('hd', 4, 0, True), ('hd', 2, 0, False)]:
            with self.subTest(quality=quality, codec=codec):
                portal = SimpleNamespace(config=AsyncMock(return_value={
                    'supportsWebrtc': True, 'motoId': 'synthetic-moto', 'auth': 'synthetic-auth',
                    'p2pConfig': {'ices': [{'urls': 'stun:example.invalid'}]},
                    'skill': json.dumps({'videos': [{'streamType': 2, 'codecType': codec}, {'streamType': 4, 'codecType': 2}]})}), routes={})
                session = RtcSession(None, 'camera', lambda _: None, portal, quality)
                config = await session.prepare()
                self.assertEqual(config['hevc'], hevc)
                self.assertEqual(config['codec'], codec if quality == 'hd' else 2)
                session.moto.async_send_webrtc_offer = AsyncMock()
                session.offer = 'synthetic-sdp'
                await session.send_offer()
                session.moto.async_send_webrtc_offer.assert_awaited_once_with(
                    'synthetic-sdp', [{'urls': 'stun:example.invalid'}], 'synthetic-auth',
                    stream_type=stream_type, datachannel_enable=hevc)

    def test_unknown_quality_is_rejected(self):
        with self.assertRaises(ValueError): RtcSession(None, 'camera', lambda _: None, None, '4k')




class ResolutionCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_connected_h264_camera_gets_explicit_hd_command(self):
        session = RtcSession(None, 'camera', lambda _: None, None, 'hd')
        session.moto = SimpleNamespace(send=AsyncMock())
        await session.signal('resolution', '0')
        session.moto.send.assert_awaited_once_with('resolution', {'mode': 'webrtc', 'cmdValue': 0}, protocol=312)
        with self.assertRaises(ValueError): await session.signal('resolution', '1')

if __name__ == '__main__': unittest.main()
