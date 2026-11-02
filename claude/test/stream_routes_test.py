import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'ops'))
import stream_routes

LIB = Path(__file__).resolve().parents[2]
INGRESS = """# comment
originRequest:
  noTLSVerify: true
ingress:
  - hostname: mygw.nekomaneki.work
    path: ^/ssh
    service: ssh://127.0.0.1:2222
  - hostname: mygw.nekomaneki.work
    service: https://127.0.0.1:8443
    originRequest:
      noTLSVerify: true
  - hostname: "stream.next.example"   # second public host of the same container
    service: https://localhost:8443
  - hostname: other.example
    service: http://127.0.0.1:3000
  - service: http_status:404
"""


class StreamRoutesTest(unittest.TestCase):
    def ingress(self, text=INGRESS):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'ingress.yml'
        path.write_text(text)
        return path

    def test_public_hosts_are_those_routed_to_the_stream_server_without_a_path(self):
        self.assertEqual(stream_routes.stream_hostnames(self.ingress()), ['mygw.nekomaneki.work', 'stream.next.example'])

    def test_unrendered_template_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):
            stream_routes.stream_hostnames(self.ingress(INGRESS.replace('mygw.nekomaneki.work', '__NEKOROOT_HOSTNAME__')))

    def test_endpoints_match_the_paths_the_lib_clients_use(self):
        endpoints = stream_routes.endpoints('https://stream.next.example')
        self.assertEqual(endpoints, {
            'embed': 'https://stream.next.example/lib/conversation-embed.html',
            'websocket': 'wss://stream.next.example/lib/api/chat/ws',
            'sse': 'https://stream.next.example/lib/api/chat/sse',
            'ndjson': 'https://stream.next.example/lib/api/chat/ndjson',
            'jsonseq': 'https://stream.next.example/lib/api/chat/jsonseq',
        })
        # Contract with the clients served from this checkout (same-origin paths).
        self.assertTrue((LIB / 'conversation-embed.html').is_file())
        self.assertIn("new URL('/lib/api/chat/ws', location.href)", (LIB / 'chat/app.mjs').read_text())
        self.assertIn('`/lib/api/chat/${this.protocol}`', (LIB / 'chat/http-stream.mjs').read_text())
        for protocol in ('sse', 'ndjson', 'jsonseq'):
            self.assertIn(f"'{protocol}'", (LIB / 'chat/app.mjs').read_text())

    def test_chat_origins_keep_existing_values_and_add_the_tunnel_hosts(self):
        self.assertEqual(stream_routes.chat_origins(['mygw.nekomaneki.work', 'stream.next.example'], 'https://legacy.example, https://mygw.nekomaneki.work'),
                         'https://legacy.example,https://mygw.nekomaneki.work,https://stream.next.example')

    def test_worker_routes_are_valid_ledger_entries(self):
        routes = stream_routes.worker_routes(['mygw.nekomaneki.work', 'stream.next.example'], route_id='next')
        self.assertEqual(routes, [{'id': 'next', 'origin': 'https://mygw.nekomaneki.work'},
                                  {'id': 'next-2', 'origin': 'https://stream.next.example'}])
        with self.assertRaises(ValueError):
            stream_routes.worker_routes(['a.example'], route_id='Bad Id')

    def test_command_line_prints_env_and_worker_ledger(self):
        path = self.ingress()
        run = lambda *args: subprocess.run([sys.executable, str(Path(stream_routes.__file__)), *args, '--ingress', str(path)],
                                           capture_output=True, text=True, env={**os.environ, 'LIB_CHAT_ORIGINS': ''}, check=True).stdout
        self.assertEqual(run('env'), 'LIB_CHAT_ORIGINS=https://mygw.nekomaneki.work,https://stream.next.example\n')
        ledger = json.loads(run('worker', '--id', 'mygw'))
        self.assertEqual(ledger, [{'id': 'mygw', 'origin': 'https://mygw.nekomaneki.work'}, {'id': 'mygw-2', 'origin': 'https://stream.next.example'}])


if __name__ == '__main__':
    unittest.main()
