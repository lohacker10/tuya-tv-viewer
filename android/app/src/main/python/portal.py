"""Exchange an authenticated mobile login for a separate Tuya web session."""
import asyncio
import http.cookiejar
import json
import logging
import contextlib
import time
from uuid import uuid4
from tuya_ipc_p2p_sdk.signaling.mqtt import MqttClient
from urllib.request import build_opener, HTTPCookieProcessor, Request


class PortalError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(f'Portale Tuya: {code}')

    @property
    def session_expired(self):
        return self.code in ('USER_SESSION_LOSS', 'USER_SESSION_INVALID')


class PortalSession:
    def __init__(self):
        self.base = 'https://protect-eu.ismartlife.me'
        self.cookies = http.cookiejar.CookieJar()
        self.http = build_opener(HTTPCookieProcessor(self.cookies))
        self.sid = ''
        self.mqtt = None
        self.reader = None
        self.msid = ''
        self.routes = {}
        self.lock = asyncio.Lock()

    def _post(self, path, body):
        headers = {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                   'Origin': self.base, 'Referer': self.base + '/login'}
        # Only the web SID returned by the portal is sent here; never the mobile SID.
        if self.sid: headers['s-sid'] = self.sid
        for cookie in self.cookies:
            if cookie.name == 'csrf-token': headers['csrf-token'] = cookie.value
        request = Request(self.base + path, data=json.dumps(body).encode(), headers=headers)
        with self.http.open(request, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict) or not data.get('success'):
            code = data.get('errorCode') if isinstance(data, dict) else 'INVALID_RESPONSE'
            raise PortalError(code)
        return data.get('result')

    async def post(self, path, body=None):
        return await asyncio.to_thread(self._post, path, body or {})

    async def authenticate(self, client):
        token = await self.post('/api/login/security/QCtoken')
        if not isinstance(token, str) or not token:
            raise RuntimeError('Token di scambio Tuya non valido')
        async def authorize(account):
            homes = await client._gateway.async_call('m.life.home.space.list', '1.0', {}, account)
            if not isinstance(homes, list) or not homes:
                raise RuntimeError('Nessuna casa Tuya disponibile')
            home_id = homes[0].get('gid')
            if not isinstance(home_id, int):
                raise RuntimeError('Casa Tuya non valida')
            await client._gateway.async_call('m.life.user.qrcode.login', '1.0',
                {'qrCode': token, 'homeId': home_id, 'terminalId': account.device_fingerprint}, account)
        await client._async_with_session(authorize)
        for _ in range(10):
            result = await self.post('/api/login/poll', {'token': token})
            if isinstance(result, dict) and isinstance(result.get('sid'), str):
                self.sid = result['sid']
                logging.info('RTC portal separate web session obtained')
                return
            await asyncio.sleep(1)
        raise RuntimeError('Scambio della sessione web Tuya scaduto')

    async def connect(self, client):
        async with self.lock:
            if self.mqtt is not None and self.reader is not None and not self.reader.done():
                return
            await self.close()
            if not self.sid:
                await self.authenticate(client)
            try:
                credentials = await self.post('/api/jarvis/mqtt')
            except PortalError as error:
                if not error.session_expired: raise
                await self.authenticate(client)
                credentials = await self.post('/api/jarvis/mqtt')
            if not isinstance(credentials, dict) or not all(isinstance(credentials.get(key), str) for key in ('msid', 'password')):
                raise RuntimeError('Credenziali del broker web non valide')
            self.msid = credentials['msid']
            self.mqtt = MqttClient(hostname='m1.tuyaeu.com', port=443,
                username='web_' + self.msid, password=credentials['password'],
                identifier='web_' + self.msid, websocket_path='/mqtt')
            try:
                async with asyncio.timeout(20):
                    await self.mqtt.__aenter__()
                    self.mqtt.start_reader()
                    await self.mqtt.subscribe('/av/u/' + self.msid)
            except BaseException:
                await self.close()
                raise
            self.reader = asyncio.create_task(self.read_messages())
            logging.info('RTC portal MQTT connected')

    async def read_messages(self):
        try:
            async for message in self.mqtt.messages():
                try:
                    envelope = json.loads(message.payload)
                    data = envelope.get('data', {})
                    header, body = data.get('header', {}), data.get('msg', {})
                    route = self.routes.get(header.get('sessionid'))
                    if route is not None and envelope.get('protocol') == 302:
                        route.consume(header.get('type'), body)
                except (ValueError, AttributeError, TypeError):
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            for route in list(self.routes.values()): route.event('error', 'Segnalazione web interrotta')

    async def config(self, client, device_id, session_id):
        await self.connect(client)
        body = {'devId': device_id, 'clientTraceId': session_id}
        try:
            result = await self.post('/api/jarvis/config', body)
        except PortalError as error:
            if not error.session_expired: raise
            for route in list(self.routes.values()): route.event('error', 'Rinnovo della sessione web…')
            await self.close()
            self.sid = ''
            self.cookies.clear()
            await self.connect(client)
            result = await self.post('/api/jarvis/config', body)
        if not isinstance(result, dict): raise RuntimeError('Configurazione web non valida')
        return result

    async def close(self):
        if self.reader is not None:
            self.reader.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.reader
            self.reader = None
        if self.mqtt is not None:
            await self.mqtt.async_close()
            self.mqtt = None
        self.routes.clear()


class PortalMoto:
    def __init__(self, portal, device_id, session_id, config, event):
        self.portal, self.device_id, self.session_id = portal, device_id, session_id
        self.moto_id, self.event = config['motoId'], event
        self.protocol = config.get('protocolVersion') or '2.2'
        self.target = config.get('gatewayId') if config.get('sub') else device_id
        self.node_id = config.get('nodeId') if config.get('sub') else '' 

    def consume(self, kind, body):
        if not isinstance(body, dict): return
        if kind == 'answer' and isinstance(body.get('sdp'), str): self.event('answer', body['sdp'])
        elif kind == 'candidate' and isinstance(body.get('candidate'), str): self.event('candidate', body['candidate'])
        elif kind == 'disconnect': self.event('error', 'La telecamera ha chiuso la connessione web')

    async def send(self, kind, body, protocol=302):
        if self.portal.mqtt is None: raise ConnectionError('Broker web non connesso')
        data = {'protocol': protocol, 'pv': self.protocol, 't': int(time.time() * 1000), 'data': {
            'header': {'from': self.portal.msid, 'to': self.target, 'sub_dev_id': self.node_id,
                'sessionid': self.session_id, 'moto_id': self.moto_id, 'seq': 0, 'rtx': 0,
                'type': kind, 'tid': str(uuid4())}, 'msg': body}}
        await self.portal.mqtt.publish('/av/moto/' + self.moto_id + '/u/' + self.target, json.dumps(data).encode())

    async def async_send_webrtc_offer(self, sdp, ice_servers, auth, stream_type=1, datachannel_enable=False):
        await self.send('offer', {'sdp': sdp, 'auth': auth, 'mode': 'webrtc',
            'datachannel_enable': datachannel_enable, 'token': ice_servers, 'stream_type': stream_type, 'replay': {'is_replay': 0}})

    async def async_send_webrtc_candidate(self, candidate):
        if candidate and not candidate.startswith('a='): candidate = 'a=' + candidate
        await self.send('candidate', {'candidate': candidate, 'mode': 'webrtc'})

    async def async_send_disconnect(self):
        await self.send('disconnect', {}, protocol=312)

    async def async_close(self):
        self.portal.routes.pop(self.session_id, None)
