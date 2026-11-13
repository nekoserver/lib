"""lib-chat.conf: the chat routes record which caller embedded them (a non-secret route id, 2026-11-13).

The embed URL carries ?via=<id>; Apache keeps it in a cookie so that the page's own requests (assets,
session, SSE, WebSocket) are attributed too, and writes it to /var/log/apache2/lib-chat-via.log.
The page signs fixed paths, so the id never goes into the API paths.
"""
import http.server
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

CONF = Path(__file__).parents[1] / 'ops/apache-lib-chat.conf'
RESTORE = Path(__file__).parents[1] / 'ops/restore-claude-host.sh'
APACHE = '/usr/sbin/apache2'
MODULES = Path('/usr/lib/apache2/modules')


class LibChatConfTest(unittest.TestCase):
    def test_route_ids_are_an_allowlist_and_precede_the_proxy_rules(self):
        conf = CONF.read_text()
        self.assertIn('via=(treeview-worker|aichat-panel)', conf)
        self.assertIn('lib_chat_via=(treeview-worker|aichat-panel)', conf)
        self.assertLess(conf.index('E=LIB_CHAT_VIA:unknown'), conf.index('[P,L]'))

    def test_cookie_matches_the_session_cookie_attributes(self):
        # The stream iframe is third-party: the session cookie works there only as Partitioned.
        line = next(l for l in CONF.read_text().splitlines() if 'Set-Cookie' in l)
        for attr in ('Path=/lib/', 'Secure', 'HttpOnly', 'SameSite=None', 'Partitioned'):
            self.assertIn(attr, line)

    def test_restore_enables_mod_headers(self):
        self.assertIn('a2enmod headers', RESTORE.read_text())


class _Backend(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(Path(APACHE).exists() and (MODULES / 'mod_headers.so').exists(), 'needs the host Apache')
class LibChatApacheTest(unittest.TestCase):
    """Runs a throwaway Apache on a free port with lib-chat.conf; the host's Apache is not touched."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        backend = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Backend)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        cls.backend = backend
        cls.port = free_port()
        cls.log = root / 'lib-chat-via.log'
        conf = CONF.read_text().replace('127.0.0.1:8092', f'127.0.0.1:{backend.server_port}') \
            .replace('/var/log/apache2/lib-chat-via.log', str(cls.log))
        (root / 'lib-chat.conf').write_text(conf)
        mods = ''.join(f'LoadModule {m}_module {MODULES}/mod_{m}.so\n'
                       for m in ('mpm_event', 'authz_core', 'rewrite', 'headers', 'proxy', 'proxy_http', 'proxy_wstunnel'))
        (root / 'httpd.conf').write_text(f'''{mods}ServerRoot {root}
PidFile {root}/httpd.pid
ErrorLog {root}/error.log
Listen 127.0.0.1:{cls.port}
ServerName localhost
<VirtualHost 127.0.0.1:{cls.port}>
    <LocationMatch "^/lib(?:$|/(?!api/tunnels(?:[.]rb)?$))">
        Require all denied
    </LocationMatch>
    RewriteEngine On
    Include {root}/lib-chat.conf
</VirtualHost>
''')
        subprocess.run([APACHE, '-f', str(root / 'httpd.conf'), '-k', 'start'], check=True)
        cls.root = root
        for _ in range(40):
            try:
                socket.create_connection(('127.0.0.1', cls.port), 0.5).close()
                break
            except OSError:
                time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        subprocess.run([APACHE, '-f', str(cls.root / 'httpd.conf'), '-k', 'stop'], check=False)
        time.sleep(0.5)
        cls.backend.shutdown()
        cls.tmp.cleanup()

    def get(self, path, cookie=None):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers={'Cookie': cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers.get_all('Set-Cookie') or []
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get_all('Set-Cookie') or []

    def log_lines(self, path):
        time.sleep(0.3)
        return [l for l in self.log.read_text().splitlines() if f' {path} ' in l or f' {path}"' in l]

    def test_embed_with_a_known_id_sets_the_cookie_and_logs_it(self):
        status, cookies = self.get('/lib/conversation-embed.html?via=treeview-worker')
        self.assertEqual(status, 200)
        self.assertTrue(any(c.startswith('lib_chat_via=treeview-worker;') for c in cookies), cookies)
        self.assertIn('via=treeview-worker', self.log_lines('/lib/conversation-embed.html')[-1])

    def test_later_requests_are_attributed_by_the_cookie(self):
        status, cookies = self.get('/lib/chat/app.mjs', cookie='lib_chat_via=aichat-panel')
        self.assertEqual(status, 200)
        self.assertEqual(cookies, [])
        self.assertIn('via=aichat-panel', self.log_lines('/lib/chat/app.mjs')[-1])

    def test_unknown_or_missing_ids_are_logged_as_unknown_without_a_cookie(self):
        status, cookies = self.get('/lib/api/chat/sse?via=evil')
        self.assertEqual(status, 200)
        self.assertEqual(cookies, [])
        self.assertIn('via=unknown', self.log_lines('/lib/api/chat/sse')[-1])

    def test_other_lib_paths_stay_denied_and_unlogged(self):
        status, _ = self.get('/lib/ip.shtml?via=treeview-worker')
        self.assertEqual(status, 403)
        self.assertEqual(self.log_lines('/lib/ip.shtml'), [])


if __name__ == '__main__':
    unittest.main()
