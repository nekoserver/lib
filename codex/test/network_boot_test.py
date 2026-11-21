"""ネットワーク起動処理の順序と CLI を隔離した Bash で検査する。"""
import os
from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'ops/network-boot.sh'
ENV = {'PATH': os.defpath, 'LANG': 'C.UTF-8'}
STUBS = r'''
source "$1"
shift
here=/fixture/codex/ops
tests=/fixture/cf-container/ops/test
restore_apache() { printf 'apache\n'; }
function /fixture/codex/ops/enable-codex-prompt.sh { printf 'auth\n'; }
function /usr/bin/python3 { printf 'python:%s\n' "$*"; }
curl() {
    local url=${!#}
    printf 'curl:%s\n' "$url"
    [[ "$url" != "$failed_url" ]]
}
apt() { printf 'apt:%s\n' "$*"; }
capture_firewall() { printf 'snapshot\n'; }
failed_url=$1
shift
run_checks "$@"
'''


class NetworkBootTest(unittest.TestCase):
    def bash(self, *args):
        return subprocess.run(
            ['bash', '--noprofile', '--norc', *args],
            env=ENV, capture_output=True, text=True, timeout=5,
        )

    def checks(self, prompt=0, panel=0, failed_url=''):
        return self.bash('-c', STUBS, 'test', str(SCRIPT), failed_url, str(prompt), str(panel))

    def test_help_and_invalid_option(self):
        help_result = self.bash(str(SCRIPT), '--help')
        self.assertEqual(help_result.returncode, 0)
        self.assertIn('[--prompt] [--panel]', help_result.stdout)
        invalid = self.bash(str(SCRIPT), '--unknown')
        self.assertEqual(invalid.returncode, 2)
        self.assertIn('--unknown', invalid.stderr)

    def test_default_checks_connection_without_creating_a_model_turn(self):
        result = self.checks()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('network_settings_test.py', result.stdout)
        self.assertIn('network_runtime_test.py', result.stdout)
        self.assertIn('network-boot-live.py\n', result.stdout)
        self.assertNotIn(' --prompt', result.stdout)
        self.assertNotIn(' --browser', result.stdout)
        self.assertLess(result.stdout.index('apt:list --upgradable'), result.stdout.index('snapshot'))
        self.assertIn('失敗項目=0', result.stdout)

    def test_live_checks_are_independently_opt_in(self):
        for prompt, panel in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(prompt=prompt, panel=panel):
                result = self.checks(prompt=prompt, panel=panel)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count('network-boot-live.py --prompt'), prompt)
                self.assertEqual(result.stdout.count('network-boot-live.py --browser'), panel)

    def test_failed_route_returns_failure_and_still_collects_firewall(self):
        result = self.checks(failed_url='https://stream.test.cfc/')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('[失敗] stream.test.cfc', result.stdout)
        self.assertIn('[成功] r9.nekomaneki.work', result.stdout)
        self.assertIn('[成功] ファイアウォール採取', result.stdout)
        self.assertIn('失敗項目=1', result.stdout)


if __name__ == '__main__':
    unittest.main()
