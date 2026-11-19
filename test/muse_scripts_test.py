"""muse/ のスクリプトとダッシュボードのテスト。

故障想定:
- 処理順(優先度の降順、同点は作成順)や件数が間違う / 壊れたJSONで全体が止まる
- 置き場所が無いときに黙って成功する
- グラフのHTMLにラベルの &<>" が混ざる、幅が100%を超える、最大値0で割る
- 「読み取り専用」なのに状態を変えるコマンド(tailscale CLI など)を呼ぶ
- ダッシュボードの断片が存在しないスクリプトを指す、エスケープし忘れる
- SSIの #exec で直接実行されるのに、実行権限が無い
外部コマンド(ps・free・df・ss・curl・pgrep・dpkg-query)は PATH の先頭に置いた偽物に差し替える。
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).parents[1]
MUSE = ROOT / 'muse'
DASHBOARD = MUSE / 'dashboard'
# SPEC.scripts.md の表にある読み取り用スクリプト。sdk-*.sh などの実行経路(SPEC.md)は、読み取り専用の規則の対象外。
READ_ONLY_SCRIPTS = ['boot-state.sh', 'bridge-jobs.sh', 'cron-state.sh', 'git-heads.sh', 'graphs.sh',
                     'muse-status.sh', 'pkg-versions.sh', 'ports.sh', 'procs.sh', 'recent-jobs.sh',
                     'tailnet-health.sh', 'vm-info.sh']
SH = shutil.which('dash') or 'sh'


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.calls = self.root / 'calls.log'

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name, body):
        """偽のコマンドを置く。呼ばれたことは calls.log に残る。"""
        path = self.bin / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\n{body}\n')
        path.chmod(0o755)

    def run_script(self, name, *args, extra_env=None):
        env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.home), 'LANG': 'C.UTF-8'}
        if extra_env:
            env.update(extra_env)
        return subprocess.run([SH, str(MUSE / name), *args], capture_output=True, text=True, env=env, timeout=30)

    def called(self):
        return self.calls.read_text() if self.calls.exists() else ''


class BridgeJobsTest(ScriptCase):
    def write_job(self, queue, name, **job):
        (queue / f'{name}.json').write_text(json.dumps(job), encoding='utf-8')

    def test_lists_queued_jobs_by_priority_then_created_and_counts_done(self):
        base = self.root / 'jobs'
        queue = base / 'queue'
        done = base / 'done'
        queue.mkdir(parents=True)
        done.mkdir()
        self.write_job(queue, 'a', job_id='low-old', status='queued', priority=1, created=100, request='低い')
        self.write_job(queue, 'b', job_id='high-new', status='queued', priority=5, created=300, request='高い・新しい')
        self.write_job(queue, 'c', job_id='high-old', status='queued', priority=5, created=200, request='一行目\n二行目')
        self.write_job(queue, 'd', job_id='claimed', status='claimed', priority=9, created=1, request='取り出し済み')
        self.write_job(queue, 'e', job_id='no-prio', status='queued', created=50, request='x' * 200)
        (queue / 'broken.json').write_text('{not json', encoding='utf-8')
        for i in range(3):
            (done / f'{i}.json').write_text('{}')
        r = self.run_script('bridge-jobs.sh', str(base))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        ids = [line.split()[2] for line in lines if line.startswith('prio ')]
        self.assertEqual(ids, ['high-old', 'high-new', 'low-old', 'no-prio'])
        self.assertIn('一行目 二行目', r.stdout)
        self.assertNotIn('claimed', ids)
        self.assertIn('(unreadable: broken.json', r.stdout)
        long_line = next(line for line in lines if 'no-prio' in line)
        self.assertEqual(long_line.count('x'), 80)
        self.assertEqual(lines[-1], 'done: 3')

    def test_empty_queue_says_zero(self):
        base = self.root / 'jobs'
        (base / 'queue').mkdir(parents=True)
        r = self.run_script('bridge-jobs.sh', str(base))
        self.assertEqual(r.returncode, 0)
        self.assertIn('queued: 0', r.stdout)
        self.assertNotIn('done:', r.stdout)

    def test_missing_queue_fails_with_reason(self):
        r = self.run_script('bridge-jobs.sh', str(self.root / 'nowhere'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('queue not found', r.stderr)

    def test_defaults_to_workspace_under_home(self):
        (self.home / 'workspace' / 'bridge-jobs' / 'queue').mkdir(parents=True)
        r = self.run_script('bridge-jobs.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('queued: 0', r.stdout)


class RecentJobsTest(ScriptCase):
    def test_lists_newest_ten_with_heading_or_file_name(self):
        done = self.root / 'jobs' / 'done'
        done.mkdir(parents=True)
        now = time.time()
        for i in range(12):
            f = done / f'job-{i:02d}.md'
            f.write_text(f'# 見出し{i}\n本文\n' if i % 2 == 0 else '見出しなし\n', encoding='utf-8')
            os.utime(f, (now - 1000 + i, now - 1000 + i))
        r = self.run_script('recent-jobs.sh', str(self.root / 'jobs'))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 10)
        self.assertTrue(lines[0].endswith('job-11'), lines[0])
        self.assertTrue(lines[1].endswith('見出し10'), lines[1])
        self.assertRegex(lines[0], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}  ')

    def test_missing_done_dir_fails_with_reason(self):
        r = self.run_script('recent-jobs.sh', str(self.root / 'nowhere'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('done dir not found', r.stderr)


class GraphsTest(ScriptCase):
    def test_bars_are_escaped_capped_and_safe_with_zero_max(self):
        self.stub('ps', '''case "$*" in
  *comm=,rss=*) printf '%s\\n' 'a<b>&"c 2048000' 'node 1024000' ;;
  *) echo 2048000 ;;
esac''')
        self.stub('free', "printf '%s\\n' 'total used' 'Mem: 1000 1500 0' 'Swap: 0 0 0'")
        self.stub('df', "printf '%s\\n' 'Filesystem 1024-blocks Used Available Capacity Mounted' '/dev/a 2048000 1024000 0 50% /' '/dev/a 2048000 1024000 0 50% /'")
        r = self.run_script('graphs.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn('<span class="glabel">abc</span>', out)
        self.assertNotRegex(re.sub(r'<[^>]+>', '', out), r'[&<>"]')
        self.assertIn('width:100%', out)
        self.assertIn('<span class="glabel">node</span><span class="gbar" style="width:50%">', out)
        self.assertIn('<span class="glabel">Swap</span><span class="gbar" style="width:0%">', out)
        self.assertEqual(out.count('<span class="glabel">/</span>'), 1)
        widths = [int(w) for w in re.findall(r'width:(\d+)%', out)]
        self.assertTrue(all(0 <= w <= 100 for w in widths), widths)


class MuseStatusTest(ScriptCase):
    def test_reports_missing_daemon_and_dead_bridge_without_touching_tailscale(self):
        self.stub('pgrep', 'exit 1')
        self.stub('curl', 'exit 7')
        self.stub('tailscale', 'exit 0')
        self.stub('uptime', 'echo " 10:00 up 1 day"')
        r = self.run_script('muse-status.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('not running', r.stdout)
        self.assertIn('(no response)', r.stdout)
        self.assertNotIn('tailscale ', self.called())
        self.assertIn('curl -s -m 5 http://127.0.0.1:8080/health', self.called())

    def test_reports_pid_and_health(self):
        self.stub('pgrep', 'echo 4242')
        self.stub('ps', 'echo "Mon Nov 10 09:00:00 2026"')
        self.stub('curl', 'printf \'{"status":"ok"}\'')
        self.stub('uptime', 'echo up')
        r = self.run_script('muse-status.sh')
        self.assertIn('PID: 4242', r.stdout)
        self.assertIn('started: Mon Nov 10 09:00:00 2026', r.stdout)
        self.assertIn('{"status":"ok"}', r.stdout)


class TailnetHealthTest(ScriptCase):
    # SPEC.lib.tailnet-health.shtml (REQ-TH-003〜009、版2で REQ-TH-011〜013)。
    # LocalAPI の応答の形は前提 P2 の実測に基づく。内容の表示は、配信側が立てる
    # フラグ MUSE_TAILNET_HEALTH_OK=1 がある場合だけ (REQ-TH-011)。
    FLAG = {'MUSE_TAILNET_HEALTH_OK': '1'}
    LOCALAPI_JSON = ('{"Version": "1.104.5", "BackendState": "Running", '
                     '"TailscaleIPs": ["100.64.0.1", "fd7a:115c:a1e0::1"], '
                     '"Self": {"HostName": "muse-vm", "DNSName": "muse-vm.example.ts.net.", '
                     '"Online": true, "PublicKey": "nodekey:SECRETKEY"}}')

    def stub_curl(self, localapi_body):
        self.stub('curl', f'''case "$*" in
  *localapi*) {localapi_body} ;;
  *8090*) printf '{{"status": "ok"}}' ;;
  *8080*) printf '{{"status": "ok"}}' ;;
  *) exit 7 ;;
esac''')

    def test_reports_node_state_ip_and_healths(self):
        self.stub('pgrep', 'echo 4242')
        self.stub('ps', 'echo "Mon Nov 10 09:00:00 2026"')
        self.stub_curl(f"printf '%s' '{self.LOCALAPI_JSON}'")
        r = self.run_script('tailnet-health.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('PID: 4242', r.stdout)
        self.assertIn('started: Mon Nov 10 09:00:00 2026', r.stdout)
        self.assertIn('state: Running', r.stdout)
        self.assertIn('version: 1.104.5', r.stdout)
        self.assertIn('IPv4: 100.64.0.1', r.stdout)
        self.assertIn('host: muse-vm', r.stdout)
        self.assertIn('DNS: muse-vm.example.ts.net.', r.stdout)
        self.assertIn('online: true', r.stdout)
        self.assertEqual(r.stdout.count('{"status": "ok"}'), 2)
        self.assertNotIn('SECRETKEY', r.stdout)
        self.assertNotIn('tailscale ', self.called())
        self.assertIn('curl -s -m 5 --unix-socket /var/run/tailscale/tailscaled.sock http://local-tailscaled.sock/localapi/v0/status', self.called())

    def test_reports_unavailable_when_localapi_fails(self):
        self.stub('pgrep', 'echo 4242')
        self.stub('ps', 'echo "Mon Nov 10 09:00:00 2026"')
        self.stub_curl('exit 7')
        r = self.run_script('tailnet-health.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(local API unavailable)', r.stdout)
        self.assertEqual(r.stdout.count('{"status": "ok"}'), 2)

    def test_reports_no_ipv4_when_only_ipv6(self):
        self.stub('pgrep', 'echo 4242')
        self.stub('ps', 'echo "Mon Nov 10 09:00:00 2026"')
        body = ('{"Version": "1.104.5", "BackendState": "Running", '
                '"TailscaleIPs": ["fd7a:115c:a1e0::1"], '
                '"Self": {"HostName": "muse-vm", "DNSName": "muse-vm.example.ts.net.", "Online": false}}')
        self.stub_curl(f"printf '%s' '{body}'")
        r = self.run_script('tailnet-health.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('IPv4: (no IPv4)', r.stdout)
        self.assertIn('online: false', r.stdout)

    def test_reports_missing_daemon_and_dead_endpoints(self):
        self.stub('pgrep', 'exit 1')
        self.stub('curl', 'exit 7')
        r = self.run_script('tailnet-health.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('not running', r.stdout)
        self.assertIn('(local API unavailable)', r.stdout)
        self.assertEqual(r.stdout.count('(no response)'), 2)

    def stub_all_healthy(self):
        self.stub('pgrep', 'echo 4242')
        self.stub('ps', 'echo "Mon Nov 10 09:00:00 2026"')
        self.stub_curl(f"printf '%s' '{self.LOCALAPI_JSON}'")

    def test_denies_without_flag(self):
        # REQ-TH-011 (AC-TH-005): フラグが無ければ、取得が全部成功する条件でも
        # 拒否の1行だけで、ノード情報を一切出さず、外部コマンドも呼ばない。
        self.stub_all_healthy()
        r = self.run_script('tailnet-health.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '(access denied)')
        self.assertNotIn('PID', r.stdout)
        self.assertNotIn('Running', r.stdout)
        self.assertNotIn('100.64.0.1', r.stdout)
        self.assertNotIn('{"status"', r.stdout)
        self.assertEqual(self.called(), '')

    def test_denies_with_wrong_flag_value(self):
        self.stub_all_healthy()
        for value in ('0', 'yes', ''):
            r = self.run_script('tailnet-health.sh', extra_env={'MUSE_TAILNET_HEALTH_OK': value})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '(access denied)', value)
            self.assertNotIn('100.64.0.1', r.stdout)

    def test_readme_has_setenvif_sample_with_placeholder(self):
        # REQ-TH-012 (AC-TH-006, 版3): 配信側の設定サンプルが dashboard/README.md にあり、
        # フラグを立てる SetEnvIf の行が X-Forwarded-User ヘッダを照合対象とし、
        # ユーザー名はプレースホルダ。判定はフラグを立てる行だけを対象とする
        # (README の説明文中の語の有無では判定しない)。
        readme = (DASHBOARD / 'README.md').read_text(encoding='utf-8')
        flag_lines = [line for line in readme.splitlines()
                      if 'SetEnvIf' in line and 'MUSE_TAILNET_HEALTH_OK=1' in line]
        self.assertTrue(flag_lines, 'no SetEnvIf line sets MUSE_TAILNET_HEALTH_OK=1')
        for line in flag_lines:
            self.assertIn('X-Forwarded-User', line)
            self.assertIn('REGULAR_USER', line)
            self.assertNotIn('REMOTE_USER', line)


class BootStateTest(ScriptCase):
    # SPEC.lib.dashboard-state.shtml (REQ-DS-001、REQ-BS-001〜005)。
    # 版の前後は実物の dpkg --compare-versions で判定する (PATH に /usr/bin が入る)。
    FLAG = {'MUSE_TAILNET_HEALTH_OK': '1'}
    FIXED_JSON = {'rows': [
        {'env': 'この VM', 'component': 'APT', 'fixed': '2.8.4ubuntu0.1'},
        {'env': 'この VM', 'component': 'Node.js (nodesource)', 'fixed': '24.22.3'},
        {'env': 'この VM', 'component': 'glibc (libc6)', 'fixed': '2.39-0ubuntu8.12（noble-security、出荷済み）'},
        {'env': 'この VM', 'component': 'Pillow (python3-pil)', 'fixed': '10.2.0-1ubuntu1.5（noble-security、USN-9064-1）'},
        {'env': 'demo コンテナ', 'component': 'APT', 'fixed': '9.9.9'},
    ]}

    def stub_dpkg_query(self, versions):
        cases = '\n'.join(f'  *\" {name}\") printf \'{ver}\' ;;' for name, ver in versions.items())
        self.stub('dpkg-query', f'''case \"$*\" in
{cases}
  *) exit 1 ;;
esac''')

    def write_fixed(self, data=None):
        path = self.root / 'status-data.json'
        path.write_text(json.dumps(data if data is not None else self.FIXED_JSON, ensure_ascii=False),
                        encoding='utf-8')
        return {'MUSE_BOOT_STATE_FIXED_JSON': str(path)}

    def env_no_reboot(self):
        return {'MUSE_BOOT_STATE_REBOOT_REQUIRED': str(self.root / 'no-reboot-required')}

    def test_reports_boot_id_and_applied_packages(self):
        self.stub_dpkg_query({'apt': '2.8.4ubuntu0.1', 'nodejs': '24.22.3',
                              'libc6': '2.39-0ubuntu8.12', 'python3-pil': '10.2.0-1ubuntu1.5'})
        env = {**self.FLAG, **self.write_fixed(), **self.env_no_reboot()}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.assertIn(boot_id, r.stdout)
        for ver in ('2.8.4ubuntu0.1', '24.22.3', '2.39-0ubuntu8.12', '10.2.0-1ubuntu1.5'):
            self.assertIn(ver, r.stdout)
        self.assertIn('対応済み', r.stdout)
        self.assertNotIn('>巻き戻り<', r.stdout)
        self.assertNotIn('再起動が必要', r.stdout)

    def test_reports_rolled_back_package(self):
        self.stub_dpkg_query({'apt': '2.8.3', 'nodejs': '24.22.3',
                              'libc6': '2.39-0ubuntu8.12', 'python3-pil': '10.2.0-1ubuntu1.5'})
        env = {**self.FLAG, **self.write_fixed(), **self.env_no_reboot()}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('>巻き戻り<', r.stdout)
        self.assertIn('2.8.3', r.stdout)

    def test_no_fixed_data_means_no_judgement(self):
        self.stub_dpkg_query({'apt': '2.8.3', 'nodejs': '24.22.1-1nodesource1',
                              'libc6': '2.39-0ubuntu8.9', 'python3-pil': '10.2.0-1ubuntu1.3'})
        env = {**self.FLAG, 'MUSE_BOOT_STATE_FIXED_JSON': str(self.root / 'missing.json'),
               **self.env_no_reboot()}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('判定なし', r.stdout)
        self.assertNotIn('>巻き戻り<', r.stdout)
        self.assertIn('2.8.3', r.stdout)

    def test_reports_reboot_required_when_file_exists(self):
        self.stub_dpkg_query({'apt': '2.8.4ubuntu0.1', 'nodejs': '24.22.3',
                              'libc6': '2.39-0ubuntu8.12', 'python3-pil': '10.2.0-1ubuntu1.5'})
        marker = self.root / 'reboot-required'
        marker.write_text('')
        env = {**self.FLAG, **self.write_fixed(), 'MUSE_BOOT_STATE_REBOOT_REQUIRED': str(marker)}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('再起動が必要', r.stdout)

    def test_reports_not_installed_package(self):
        self.stub_dpkg_query({'apt': '2.8.4ubuntu0.1', 'nodejs': '24.22.3',
                              'libc6': '2.39-0ubuntu8.12'})
        env = {**self.FLAG, **self.write_fixed(), **self.env_no_reboot()}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(not installed)', r.stdout)

    def test_reports_dpkg_unavailable(self):
        bindir = self.root / 'bin2'
        bindir.mkdir()
        (bindir / 'python3').symlink_to(shutil.which('python3'))
        env = {**self.FLAG, 'PATH': str(bindir), **self.env_no_reboot()}
        r = self.run_script('boot-state.sh', extra_env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(dpkg unavailable)', r.stdout)

    def test_denies_without_flag(self):
        # REQ-DS-001 (AC-DS-001): フラグが無ければ拒否の1行だけで、外部コマンドも呼ばない。
        self.stub_dpkg_query({'apt': '2.8.4ubuntu0.1', 'nodejs': '24.22.3',
                              'libc6': '2.39-0ubuntu8.12', 'python3-pil': '10.2.0-1ubuntu1.5'})
        r = self.run_script('boot-state.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '(access denied)')
        self.assertEqual(self.called(), '')


class CronStateTest(ScriptCase):
    # SPEC.lib.dashboard-state.shtml (REQ-DS-001、REQ-CS-001)。
    FLAG = {'MUSE_TAILNET_HEALTH_OK': '1'}
    STATE_REL = 'workspace/goals/musevm-kernel-build-environment/hidden_files'

    def state_dir(self):
        d = self.home / self.STATE_REL
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_reports_state_files_and_missing_ones(self):
        d = self.state_dir()
        f = d / 'vm-auto-update-state.md'
        f.write_text('# vm-auto-update 状態\n\n## 2026-11-19 10:35 の実行\n34件適用、残件0\n', encoding='utf-8')
        os.utime(f, (1795050000, 1795050000))
        r = self.run_script('cron-state.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('vm-auto-update', r.stdout)
        self.assertIn('2026-11-19 10:35 の実行', r.stdout)
        self.assertIn('vuln-watch', r.stdout)
        self.assertIn('記録なし', r.stdout)

    def test_escapes_state_file_content(self):
        # REQ-DS-002 (AC-DS-002): 状態ファイル由来の見出しは HTML エスケープして出す。
        d = self.state_dir()
        (d / 'vuln-watch-state.md').write_text('## 2026-11-19 <script>alert(1)</script>\n', encoding='utf-8')
        r = self.run_script('cron-state.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('&lt;script&gt;', r.stdout)
        self.assertNotIn('<script>alert', r.stdout)

    def test_empty_state_file(self):
        d = self.state_dir()
        (d / 'vm-auto-update-state.md').write_text('', encoding='utf-8')
        r = self.run_script('cron-state.sh', extra_env=self.FLAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(empty)', r.stdout)

    def test_denies_without_flag(self):
        d = self.state_dir()
        (d / 'vm-auto-update-state.md').write_text('## 2026-11-19 10:35 の実行\n', encoding='utf-8')
        r = self.run_script('cron-state.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '(access denied)')
        self.assertNotIn('2026-11-19', r.stdout)


class PkgVersionsTest(ScriptCase):
    def test_reads_nix_manifest_and_selected_deb_versions(self):
        profile = self.home / '.nix-profile'
        profile.mkdir()
        (profile / 'manifest.json').write_text(json.dumps({'elements': [
            {'storePaths': ['/nix/store/abc-ripgrep-14.1.1']},
            {'storePaths': ['/nix/store/def-jq-1.7.1', '/nix/store/ghi-jq-1.7.1-man']},
        ]}))
        self.stub('dpkg-query', '''case "$*" in
  *binary:Package*) printf '%s\\n' a b c ;;
  *" git") printf '1:2.47.0' ;;
  *" python3") printf '3.13.0' ;;
  *) exit 1 ;;
esac''')
        r = self.run_script('pkg-versions.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ['abc-ripgrep-14.1.1', 'def-jq-1.7.1', 'ghi-jq-1.7.1-man']:
            self.assertIn(name, r.stdout)
        self.assertIn('installed packages: 3', r.stdout)
        self.assertIn('git 1:2.47.0', r.stdout)
        self.assertIn('python3 3.13.0', r.stdout)
        self.assertNotIn('ruby ', r.stdout)

    def test_says_when_nix_is_unavailable(self):
        r = self.run_script('pkg-versions.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(nix profile unavailable)', r.stdout)


class GitHeadsTest(ScriptCase):
    def test_reports_branch_head_dirty_and_unpushed(self):
        repo = self.home / 'workspace' / 'proj'
        repo.mkdir(parents=True)
        env = {**os.environ, 'HOME': str(self.home), 'GIT_CONFIG_GLOBAL': '/dev/null',
               'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
               'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
        for cmd in (['init', '-q', '-b', 'main'], ['commit', '-q', '--allow-empty', '-m', '最初のコミット']):
            subprocess.run(['git', '-C', str(repo), *cmd], check=True, env=env)
        (repo / 'new.txt').write_text('x')
        r = self.run_script('git-heads.sh')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r'^workspace/proj \[main\] [0-9a-f]{7,} 最初のコミット \(dirty: 1, unpushed: \?\)$')


class SimpleListsTest(ScriptCase):
    def test_ports_lists_tcp_and_udp_listeners(self):
        self.stub('ss', "printf '%s\\n' 'Netid State Recv-Q Send-Q Local Peer' 'tcp LISTEN 0 128 0.0.0.0:8090 0.0.0.0:*' 'udp UNCONN 0 0 0.0.0.0:41641 0.0.0.0:*'")
        r = self.run_script('ports.sh')
        self.assertEqual(r.stdout.strip().splitlines(), ['tcp 0.0.0.0:8090', 'udp 0.0.0.0:41641'])

    def test_ports_says_when_ss_is_missing(self):
        env = {'PATH': str(self.bin), 'HOME': str(self.home)}
        r = subprocess.run([shutil.which(SH) or SH, str(MUSE / 'ports.sh')], capture_output=True, text=True, env=env)
        self.assertIn('ss not found', r.stdout)

    def test_procs_converts_rss_to_mib(self):
        self.stub('ps', "printf '%s\\n' '1 node 2048' '2 python3 1024'")
        r = self.run_script('procs.sh')
        self.assertEqual(r.stdout.strip().splitlines(), ['PID COMMAND RSS', '1 node 2.0 MiB', '2 python3 1.0 MiB'])


class ScriptRulesTest(unittest.TestCase):
    def test_scripts_are_posix_sh_with_set_u(self):
        for name in READ_ONLY_SCRIPTS:
            text = (MUSE / name).read_text(encoding='utf-8')
            self.assertTrue(text.startswith('#!/bin/sh\n'), name)
            self.assertIn('\nset -u\n', text, name)
            r = subprocess.run([SH, '-n', str(MUSE / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{name}: {r.stderr}')

    def test_scripts_do_not_change_state(self):
        forbidden = re.compile(r'(^|[\s;|&(])(rm|mv|cp|chmod|chown|kill|pkill|systemctl|service|reboot|tailscale|apt-get|nix-env -i|git (push|commit|reset|checkout|fetch|pull))\b')
        for name in READ_ONLY_SCRIPTS:
            for line in (MUSE / name).read_text(encoding='utf-8').splitlines():
                code = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                self.assertIsNone(forbidden.search(code), f'{name}: {line}')

    def test_scripts_are_executable_in_git(self):
        # dashboard の SSI は #exec cmd="../xxx.sh" で直接実行する(dashboard/README.md)。実行権限が無いと全区画が失敗する。
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-s', 'muse'], capture_output=True, text=True, check=True).stdout
        modes = {line.split()[3]: line.split()[0] for line in out.splitlines()}
        for name in DashboardTest.used_scripts():
            self.assertEqual(modes.get(f'muse/{name}'), '100755', name)

    def test_every_file_with_a_shebang_is_executable_in_git(self):
        # pending.sh は sdk-approve.sh を直接 exec する。sdk-approve.py も sdk-ask.sh を直接起動する。
        # 実行権限が無いと「Permission denied」で止まる(2026-11-11 に muse-vm で起きた)。
        # 先頭が #! のファイルは直接実行されうるので、すべて 100755 にする。読み込むだけ(sdk-common.sh など)は #! を持たない。
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-s', 'muse'], capture_output=True, text=True, check=True).stdout
        missing = []
        for line in out.splitlines():
            mode, _, _, path = line.split(None, 3)
            if mode not in ('100644', '100755'):
                continue
            with open(ROOT / path, 'rb') as f:
                if f.read(2) == b'#!' and mode != '100755':
                    missing.append(path)
        self.assertEqual(missing, [])


class DashboardTest(unittest.TestCase):
    EXEC = re.compile(r'<!--#exec cmd="([^"]*)" -->')
    ENV_PREFIX = re.compile(r'^(?:[A-Z_][A-Z0-9_]*=\S*\s+)*')

    @classmethod
    def script_of(cls, cmd):
        return cls.ENV_PREFIX.sub('', cmd).split()[0]

    @classmethod
    def used_scripts(cls):
        used = set()
        for frag in DASHBOARD.glob('*.shtml'):
            for cmd in cls.EXEC.findall(frag.read_text(encoding='utf-8')):
                used.add(cls.script_of(cmd).removeprefix('../'))
        return sorted(used)

    # 完成した HTML を出すスクリプトの一覧 (SPEC.lib.dashboard-state.shtml REQ-DS-002)。
    # これらは断片側の sed エスケープを通さず、動的な値のエスケープはスクリプト側が
    # 行う (graphs.sh の方式。エスケープ自体は各スクリプトのテストで検査する)。
    HTML_SCRIPTS = {'../graphs.sh', '../boot-state.sh', '../cron-state.sh'}

    def test_each_fragment_runs_an_existing_script_and_escapes_its_output(self):
        fragments = sorted(p for p in DASHBOARD.glob('*.shtml') if p.name != 'index.shtml')
        self.assertTrue(fragments)
        for frag in fragments:
            cmds = self.EXEC.findall(frag.read_text(encoding='utf-8'))
            self.assertEqual(len(cmds), 1, frag.name)
            script = self.script_of(cmds[0])
            self.assertTrue(script.startswith('../'), frag.name)
            self.assertTrue((DASHBOARD / script).resolve().is_file(), f'{frag.name} -> {script}')
            if script not in self.HTML_SCRIPTS:
                for needle in ("s/&/\\&amp;/g", "s/</\\&lt;/g", "s/>/\\&gt;/g", "s/$/<br>/"):
                    self.assertIn(needle, cmds[0], frag.name)

    def test_index_sections_point_to_existing_fragments_and_every_script_has_one(self):
        index = (DASHBOARD / 'index.shtml').read_text(encoding='utf-8')
        frags = re.findall(r'data-frag="([^"]+)"', index)
        self.assertTrue(frags)
        for frag in frags:
            self.assertTrue((DASHBOARD / frag).is_file(), frag)
        used = self.used_scripts()
        for name in used:
            self.assertTrue((MUSE / name).is_file(), name)
        for name in READ_ONLY_SCRIPTS:
            self.assertIn(name, used)

    def test_readme_lists_every_script(self):
        readme = (MUSE / 'README.md').read_text(encoding='utf-8')
        for name in READ_ONLY_SCRIPTS:
            self.assertIn(f'`{name}`', readme)



class PanelTest(unittest.TestCase):
    """サイドパネルとレイアウト (SPEC.lib.dashboard-state.shtml 版2、REQ-PN-001〜007)。

    表示・非表示は SSI の #if で区画そのものを切り替え、状態は Cookie から
    サーバ側で描く。前提 (Cookie を SetEnvIf で環境変数へ写し、旧式パーサの
    #if で隠した区画の #exec が実行されない) は SPEC の前提 P8 で実測済み。
    """

    @classmethod
    def setUpClass(cls):
        cls.index = (DASHBOARD / 'index.shtml').read_text(encoding='utf-8')
        cls.frags = re.findall(r'data-frag="([^"]+)"', cls.index)
        cls.ids = [f.removesuffix('.shtml') for f in cls.frags]

    def test_panel_lists_a_checkbox_for_every_read_section(self):
        self.assertIn('id="dashpanel"', self.index)
        self.assertTrue(self.ids)
        for sec_id in self.ids:
            self.assertIn(f'data-sec="{sec_id}"', self.index, sec_id)

    def test_each_section_is_wrapped_in_an_ssi_if_on_libdash_off(self):
        for sec_id in self.ids:
            cond = f'<!--#if expr="$LIBDASH_OFF != /,{sec_id},/" -->'
            self.assertIn(cond, self.index, sec_id)
            if_at = self.index.index(cond)
            sec_at = self.index.index(f'data-frag="{sec_id}.shtml"')
            self.assertLess(if_at, sec_at, sec_id)
            end_at = self.index.index('</section>', sec_at)
            self.assertIn('<!--#endif -->', self.index[end_at:end_at + 80], sec_id)

    def test_checkbox_state_is_rendered_by_ssi(self):
        for sec_id in self.ids:
            self.assertIn(
                f'<!--#if expr="$LIBDASH_OFF != /,{sec_id},/" --> checked<!--#endif -->',
                self.index, sec_id)

    def test_layout_samples_are_selectable_and_switched_by_ssi(self):
        for name in ('stack', 'grid', 'compact'):
            self.assertRegex(
                self.index,
                r'name="libdash_layout"[^>]*value="' + name + '"', name)
            self.assertIn(f'.layout-{name}', self.index, name)
        self.assertIn('expr="$LIBDASH_LAYOUT = /grid/"', self.index)
        self.assertIn('expr="$LIBDASH_LAYOUT = /compact/"', self.index)

    def test_script_writes_both_cookies_and_reloads(self):
        self.assertIn("'libdash_off=,", self.index)
        self.assertIn("'libdash_layout='", self.index)
        self.assertIn('location.reload()', self.index)


class NoticeToMuseTest(unittest.TestCase):
    """muse/NOTICE-TO-MUSE.md(Muse への伝達事項)。更新のたびに新しい日付の節を先頭に書き足す。"""

    def test_newest_first_with_dated_sections_and_actions(self):
        text = (MUSE / 'NOTICE-TO-MUSE.md').read_text(encoding='utf-8')
        dates = re.findall(r'(?m)^## (\d{4}-\d{2}-\d{2})', text)
        self.assertTrue(dates)
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertEqual(len(dates), len(set(dates)), '同じ日は1つの節にまとめる')
        for section in re.split(r'(?m)^## ', text)[1:]:
            self.assertIn('### やること', section, section.splitlines()[0])

    def test_rules_require_appending_on_every_change(self):
        rules = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertIn('muse/NOTICE-TO-MUSE.md', rules)


if __name__ == '__main__':
    unittest.main()
