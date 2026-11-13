import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'ops/restore-claude-host.sh'
SITE = """<VirtualHost *:8443>
    ProxyRequests Off
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /(.*) ws://127.0.0.1:8080/$1 [P,L]
    ProxyPass / http://127.0.0.1:8080/ retry=0
    ProxyPassReverse / http://127.0.0.1:8080/
</VirtualHost>
"""
# The demo image's vhost since 2026-11-12: lib is admin-only except the signed tunnels API
# (user decision 2026-11-11), which the image routes to the original tunnels.rb.
IMAGE_SITE = """<VirtualHost *:8443>
    <LocationMatch "^/(?:debug|admin)(?:/|$)|^/lib(?:$|/(?!api/tunnels(?:[.]rb)?$))">
        Require all denied
    </LocationMatch>
    ProxyRequests Off
    ProxyPassMatch "^/lib/api/tunnels(?:[.]rb)?$" "!"
    ScriptAliasMatch "^/lib/api/tunnels(?:[.]rb)?$" "/usr/local/libexec/lib-api/tunnels.cgi"
    RewriteEngine On
    RewriteCond %{REQUEST_URI} !^/lib/api/(?:chat/ws|tunnels(?:[.]rb)?)$
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /(.*) ws://127.0.0.1:8080/$1 [P,L]
    ProxyPass / http://127.0.0.1:8080/ retry=0
</VirtualHost>
"""


class RestoreClaudeHostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.www, self.apache = root / 'www/lib', root / 'apache2'
        (self.apache / 'sites-available').mkdir(parents=True)
        self.site = self.apache / 'sites-available/000-demo.conf'
        self.site.write_text(SITE)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, **env):
        base = {'PATH': os.environ['PATH'], 'LIB_WWW': str(self.www), 'LIB_APACHE_DIR': str(self.apache),
                'LIB_RESTORE_NO_START': '1', 'ORIGIN_HMAC_SECRET': 'hmac-test', 'CF_CONTAINER_API_TOKEN': 'cf-test'}
        return subprocess.run(['sh', str(SCRIPT)], env={**base, **env}, capture_output=True, text=True)

    def test_routes_tunnels_before_the_server_js_proxy(self):
        self.assertEqual(self.run_script().returncode, 0)
        lines = self.site.read_text().splitlines()
        include = lines.index(f'    Include {self.apache}/lib-tunnels.conf')
        self.assertLess(include, next(i for i, line in enumerate(lines) if line.strip().startswith('ProxyPass / ')))
        conf = (self.apache / 'lib-tunnels.conf').read_text()
        self.assertIn(f'Include {self.apache}/lib-secrets.conf', conf)
        self.assertIn(f'ScriptAlias /lib/api/tunnels {self.www}/claude/api/tunnels.claude.rb', conf)
        self.assertTrue((self.www / 'claude/api/tunnels.claude.rb').is_file())
        self.assertTrue((self.www / 'api/tunnels_lib.rb').is_file())

    def test_routes_chat_before_the_catch_all_websocket_rewrite(self):
        self.assertEqual(self.run_script().returncode, 0)
        lines = self.site.read_text().splitlines()
        include = lines.index(f'    Include {self.apache}/lib-chat.conf')
        self.assertEqual(lines[include - 1].strip(), 'RewriteEngine On')
        self.assertLess(include, next(i for i, line in enumerate(lines) if 'ws://127.0.0.1:8080' in line))
        conf = (self.apache / 'lib-chat.conf').read_text()
        self.assertIn('RewriteRule ^/lib/api/chat/ws$ ws://127.0.0.1:8091/lib/api/chat/ws [P,L]', conf)
        self.assertIn('http://127.0.0.1:8092/lib/$1 [P,L]', conf)
        # The stream servers run as www-data from the deployed copy.
        for name in ('ops/chat_http_stream.py', 'ops/chat_websocket.py', 'chat/app.mjs', 'conversation-embed.html'):
            self.assertTrue((self.www / name).is_file(), name)

    def test_starts_apache_without_apache2ctl(self):
        # apache2ctl hands over to systemctl here and exits 0 without doing anything.
        script = SCRIPT.read_text()
        self.assertNotIn('apache2ctl graceful', script)
        self.assertIn('/usr/sbin/apache2 -k', script)
        self.assertIn('if pgrep -x apache2 >/dev/null; then apache graceful; else apache start; fi', script)

    def test_is_idempotent(self):
        self.run_script()
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.site.read_text().count('lib-tunnels.conf'), 1)
        self.assertEqual(self.site.read_text().count('lib-chat.conf'), 1)

    def test_secrets_are_private_and_prefer_the_explicit_token(self):
        self.run_script(LIB_TUNNELS_CF_TOKEN='cf-explicit')
        secrets = self.apache / 'lib-secrets.conf'
        self.assertEqual(secrets.stat().st_mode & 0o777, 0o600)
        self.assertEqual(secrets.read_text(), 'SetEnv ORIGIN_HMAC_SECRET "hmac-test"\n'
                                              'SetEnv CF_CONTAINER_API_TOKEN "cf-explicit"\n')

    def test_image_site_routes_tunnels_before_the_image_cgi(self):
        # mod_alias takes the first matching alias, so the Include must precede the image's ScriptAliasMatch.
        self.site.write_text(IMAGE_SITE)
        self.assertEqual(self.run_script().returncode, 0)
        lines = self.site.read_text().splitlines()
        include = lines.index(f'    Include {self.apache}/lib-tunnels.conf')
        self.assertLess(include, next(i for i, line in enumerate(lines) if 'ScriptAliasMatch' in line))
        self.run_script()
        self.assertEqual(self.site.read_text().count('lib-tunnels.conf'), 1)

    def test_image_site_opens_only_the_chat_routes(self):
        # lib stays admin-only (2026-11-11), but the chat routes have their own login, HMAC session and
        # frame-ancestors; the tree-view worker tab and the AI chat panel embed them (provisional, 2026-11-13).
        self.site.write_text(IMAGE_SITE)
        self.assertEqual(self.run_script().returncode, 0)
        lines = self.site.read_text().splitlines()
        include = lines.index(f'    Include {self.apache}/lib-chat.conf')
        # Later <LocationMatch> sections override earlier ones, so the grant must come after the deny.
        self.assertGreater(include, next(i for i, line in enumerate(lines) if 'Require all denied' in line))
        conf = (self.apache / 'lib-chat.conf').read_text()
        grant = conf[conf.index('<LocationMatch'):conf.index('</LocationMatch>')]
        self.assertIn('Require all granted', grant)
        self.assertIn('conversation-embed', grant)
        self.assertIn('api/chat/', grant)
        for private in ('shtml', 'cgi', 'docker', 'api/tunnels', 'ops'):
            self.assertNotIn(private, grant)

    def test_replaces_the_original_worker_and_observer(self):
        # The image starts lib/ops/llm_worker.py and chat_observer.py on the same sockets,
        # and the start scripts do nothing while a socket answers.
        script = SCRIPT.read_text()
        stop = script.index('stop_original llm_worker.py')
        self.assertLess(stop, script.index('start-llm-worker-claude.sh"'))
        self.assertLess(script.index('stop_original chat_observer.py'), script.index('start-chat-observer-claude.sh"'))

    def test_requires_the_secret(self):
        result = self.run_script(ORIGIN_HMAC_SECRET='')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ORIGIN_HMAC_SECRET', result.stderr)
        self.assertEqual(self.site.read_text(), SITE)


if __name__ == '__main__':
    unittest.main()
