"""lib-internal-chat.conf on the demo image's internal vhost (127.0.0.1:8445).

tree-view's worker tab reaches the conversation stream through the main Worker's relay -> server.js -> 8445. The image's
010-lib.conf (2026-11-11..18) had no relay, so the tab got the static embed page and 404 for /lib/api/chat/session and
stayed blank (2026-11-18). restore-claude-host.sh Includes this file there until the image carries the relay itself
(nekoserver/cloudflare-workers-github-oauth-1#2660). Runs a throwaway Apache; the host's Apache is not touched.
"""
import http.server
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

CONF = Path(__file__).parents[1] / 'ops/apache-lib-internal-chat.conf'
APACHE = '/usr/sbin/apache2'
MODULES = Path('/usr/lib/apache2/modules')


class _Backend(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _Backend.seen.append((self.path, self.headers.get('Host')))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'stream-server')

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(Path(APACHE).exists() and (MODULES / 'mod_proxy_http.so').exists(), 'needs the host Apache')
class LibInternalChatApacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        backend = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Backend)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        cls.backend = backend
        (root / 'lib').mkdir()
        (root / 'lib/date.shtml').write_text('static')
        (root / 'lib-internal-chat.conf').write_text(
            CONF.read_text().replace('127.0.0.1:8092', f'127.0.0.1:{backend.server_port}'))
        cls.port = free_port()
        mods = ''.join(f'LoadModule {m}_module {MODULES}/mod_{m}.so\n'
                       for m in ('mpm_event', 'authz_core', 'authz_host', 'proxy', 'proxy_http', 'proxy_wstunnel'))
        (root / 'httpd.conf').write_text(f'''{mods}ServerRoot {root}
PidFile {root}/httpd.pid
ErrorLog {root}/error.log
Listen 127.0.0.1:{cls.port}
ServerName localhost
<VirtualHost 127.0.0.1:{cls.port}>
    DocumentRoot {root}
    <Directory {root}/lib>
        Require local
    </Directory>
    Include {root}/lib-internal-chat.conf
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

    def get(self, path):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', headers={'Host': 'mygw.nekomaneki.work'})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b''

    def test_the_conversation_stream_paths_reach_the_stream_server_with_the_host_kept(self):
        for path in ('/lib/api/chat/session', '/lib/conversation-embed.html', '/lib/chat/app.mjs', '/lib/t/abc/chat/app.mjs'):
            with self.subTest(path=path):
                _Backend.seen.clear()
                self.assertEqual(self.get(path), (200, b'stream-server'))
                self.assertEqual(_Backend.seen, [(path, 'mygw.nekomaneki.work')])

    def test_other_lib_paths_are_not_relayed(self):
        _Backend.seen.clear()
        self.assertEqual(self.get('/lib/date.shtml'), (200, b'static'))
        self.assertEqual(_Backend.seen, [])


if __name__ == '__main__':
    unittest.main()
