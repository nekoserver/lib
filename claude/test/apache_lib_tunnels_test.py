"""lib-tunnels.conf behind the demo vhost's admin-only deny of /lib (user decision 2026-11-11).

The main Worker's /neko askgk POSTs to the public https://<host>/lib/api/tunnels with X-Timestamp and
X-Signature. The vhost denies all of /lib, so lib-tunnels.conf (Included after the deny) must let
exactly that path through when both headers are present; the CGI then verifies the HMAC (401 if bad).
Same exception as the main repo's SPEC lib-access-control (2026-11-13), whose lib-askgk-api.conf the
demo image no longer ships (2026-11-18: askgk got HTTP 403).
"""
import http.client
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

CONF = Path(__file__).parents[1] / 'ops/apache-lib-tunnels.conf'
APACHE = '/usr/sbin/apache2'
MODULES = Path('/usr/lib/apache2/modules')
# The demo image's vhost as of 2026-11-18 (/etc/apache2/sites-available/000-demo.conf).
DENY = '''    <LocationMatch "^/(?:debug|admin|lib)(?:/|$)">
        Require all denied
    </LocationMatch>'''


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(Path(APACHE).exists() and (MODULES / 'mod_cgid.so').exists(), 'needs the host Apache')
class LibTunnelsApacheTest(unittest.TestCase):
    """Runs a throwaway Apache on a free port; the host's Apache is not touched."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cgi = root / 'tunnels.cgi'
        cgi.write_text('#!/bin/sh\ncat >/dev/null\nprintf "Content-Type: text/plain\\r\\n\\r\\ncgi"\n')
        cgi.chmod(0o755)
        (root / 'lib-secrets.conf').write_text('')
        conf = CONF.read_text().replace('/etc/apache2/lib-secrets.conf', str(root / 'lib-secrets.conf')) \
            .replace('/var/www/html/lib/claude/api/tunnels.claude.rb', str(cgi))
        (root / 'lib-tunnels.conf').write_text(conf)
        cls.port = free_port()
        mods = ''.join(f'LoadModule {m}_module {MODULES}/mod_{m}.so\n'
                       for m in ('mpm_event', 'authz_core', 'alias', 'cgid', 'env', 'proxy'))
        (root / 'httpd.conf').write_text(f'''{mods}ServerRoot {root}
PidFile {root}/httpd.pid
ErrorLog {root}/error.log
ScriptSock {root}/cgid.sock
Listen 127.0.0.1:{cls.port}
ServerName localhost
<VirtualHost 127.0.0.1:{cls.port}>
{DENY}
    Include {root}/lib-tunnels.conf
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
        # The port opens before mod_cgid's daemon is ready; an early CGI request can come back cut off.
        for _ in range(40):
            try:
                if cls.post(cls, '/lib/api/tunnels') == (200, b'cgi'):
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        subprocess.run([APACHE, '-f', str(cls.root / 'httpd.conf'), '-k', 'stop'], check=False)
        time.sleep(0.5)
        cls.tmp.cleanup()

    def post(self, path, signed=True):
        headers = {'Content-Type': 'application/json'}
        if signed:
            headers.update({'X-Timestamp': '1795000000', 'X-Signature': '0' * 64})
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{}', headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b''

    def test_a_request_with_the_signature_headers_reaches_the_cgi(self):
        self.assertEqual(self.post('/lib/api/tunnels'), (200, b'cgi'))

    def test_a_request_without_the_signature_headers_is_denied_by_apache(self):
        self.assertEqual(self.post('/lib/api/tunnels', signed=False)[0], 403)

    def test_only_the_exact_path_is_excepted(self):
        for path in ('/lib/api/tunnels/extra', '/lib/api/tunnels.rb', '/lib/ip.shtml', '/lib/api/tunnels_lib.rb'):
            with self.subTest(path=path):
                self.assertEqual(self.post(path)[0], 403)


if __name__ == '__main__':
    unittest.main()
