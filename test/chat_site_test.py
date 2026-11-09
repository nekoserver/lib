import hashlib
import hmac
from pathlib import Path
import sys
import tempfile
import time
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
from chat_site import register_site, COOKIE
from chat_session import issue
from chat_access import authorize_request

SECRET = b'test'
ORIGIN = 'https://chat.example'

class SiteTest(unittest.IsolatedAsyncioTestCase):
    def test_reusable_verifier_signs_actual_method_query_and_body(self):
        ts = str(int(time.time()))
        body = b'{"operation":"test"}'
        path = '/other/api?q=1'
        sig = hmac.new(SECRET, f'POST\n{path}\n{ts}\n{hashlib.sha256(body).hexdigest()}'.encode(), hashlib.sha256).hexdigest()
        args = dict(method='POST', path=path, body=body,
                    headers={'X-Timestamp': ts, 'X-Signature': sig}, cookies={},
                    origin=ORIGIN, allowed_origins={ORIGIN})
        self.assertTrue(authorize_request(SECRET, **args))
        for changed in [{'method': 'GET'}, {'path': '/other/api'}, {'body': b'changed'}, {'origin': 'https://evil.example'}]:
            self.assertFalse(authorize_request(SECRET, **{**args, **changed}))
        self.assertFalse(authorize_request(b'', **args))

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'chat').mkdir()
        (self.root / 'conversation-embed.html').write_text('PRIVATE HTML')
        (self.root / 'chat/app.mjs').write_text('PRIVATE JS')
        (self.root / 'chat/escape').symlink_to('/etc/passwd')
        app = web.Application()
        register_site(app, SECRET, {ORIGIN}, self.root)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def headers(self, token=None):
        h = {'Host': 'chat.example'}
        if token: h['Cookie'] = COOKIE + '=' + token
        return h

    async def test_entry_contains_only_authentication(self):
        r = await self.client.get('/', headers=self.headers())
        text = await r.text()
        self.assertEqual(r.status, 200)
        self.assertNotIn('PRIVATE', text)
        self.assertIn('crypto.subtle', text)
        self.assertIn('sessionStorage.setItem(STORAGE', text)
        self.assertIn("location.replace('/lib/t/' + data.asset_ticket", text)
        self.assertNotIn('#session=', text)
        self.assertIn('no-store', r.headers['Cache-Control'])
        self.assertIn("default-src 'none'", r.headers['Content-Security-Policy'])
        r = await self.client.get('/lib/conversation-embed.html', headers={**self.headers(), 'Accept': 'text/html'})
        self.assertEqual(r.status, 200)
        self.assertNotIn('PRIVATE HTML', await r.text())

    async def test_assets_require_valid_origin_bound_cookie(self):
        for token in [None, 'invalid', issue(SECRET, 'https://other.example'), issue(SECRET, ORIGIN, 'console')]:
            for path in ['/lib/conversation-embed.html', '/lib/chat/app.mjs']:
                r = await self.client.get(path, headers=self.headers(token))
                self.assertEqual(r.status, 401)
                self.assertNotIn('PRIVATE', await r.text())
        for path in ['/lib/conversation-embed.html', '/lib/chat/app.mjs']:
            r = await self.client.get(path, headers=self.headers(issue(SECRET, ORIGIN)))
            self.assertEqual(r.status, 200)
            self.assertIn('PRIVATE', await r.text())
            self.assertIn('no-store', r.headers['Cache-Control'])
        r = await self.client.get('/lib/chat/escape', headers=self.headers(issue(SECRET, ORIGIN)))
        self.assertEqual(r.status, 403)
        r = await self.client.get('/lib/ops/chat_site.py', headers=self.headers(issue(SECRET, ORIGIN)))
        self.assertEqual(r.status, 403)

    async def test_signature_and_expiry(self):
        path = '/lib/conversation-embed.html'
        for age, ok in [(0, True), (600, False)]:
            ts = str(int(time.time()) - age)
            sig = hmac.new(SECRET, f'GET\n{path}\n{ts}\n{hashlib.sha256(b"").hexdigest()}'.encode(), hashlib.sha256).hexdigest()
            r = await self.client.get(path, headers={**self.headers(), 'X-Timestamp': ts, 'X-Signature': sig})
            self.assertEqual(r.status, 200 if ok else 401)
        r = await self.client.get(path, headers={**self.headers(issue(SECRET, ORIGIN)), 'X-Signature': 'bad'})
        self.assertEqual(r.status, 401)
