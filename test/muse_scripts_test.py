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
SCRIPTS = sorted(p.name for p in MUSE.glob('*.sh'))
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

    def run_script(self, name, *args):
        env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.home), 'LANG': 'C.UTF-8'}
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
        for name in SCRIPTS:
            text = (MUSE / name).read_text(encoding='utf-8')
            self.assertTrue(text.startswith('#!/bin/sh\n'), name)
            self.assertIn('\nset -u\n', text, name)
            r = subprocess.run([SH, '-n', str(MUSE / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{name}: {r.stderr}')

    def test_scripts_do_not_change_state(self):
        forbidden = re.compile(r'(^|[\s;|&(])(rm|mv|cp|chmod|chown|kill|pkill|systemctl|service|reboot|tailscale|apt-get|nix-env -i|git (push|commit|reset|checkout|fetch|pull))\b')
        for name in SCRIPTS:
            for line in (MUSE / name).read_text(encoding='utf-8').splitlines():
                code = line.split('#', 1)[0] if not line.lstrip().startswith('#') else ''
                self.assertIsNone(forbidden.search(code), f'{name}: {line}')

    def test_scripts_are_executable_in_git(self):
        # dashboard の SSI は #exec cmd="../xxx.sh" で直接実行する(dashboard/README.md)。実行権限が無いと全区画が失敗する。
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '-s', 'muse'], capture_output=True, text=True, check=True).stdout
        modes = {line.split()[3]: line.split()[0] for line in out.splitlines()}
        for name in SCRIPTS:
            self.assertEqual(modes.get(f'muse/{name}'), '100755', name)


class DashboardTest(unittest.TestCase):
    EXEC = re.compile(r'<!--#exec cmd="([^"]*)" -->')

    def test_each_fragment_runs_an_existing_script_and_escapes_its_output(self):
        fragments = sorted(p for p in DASHBOARD.glob('*.shtml') if p.name != 'index.shtml')
        self.assertTrue(fragments)
        for frag in fragments:
            cmds = self.EXEC.findall(frag.read_text(encoding='utf-8'))
            self.assertEqual(len(cmds), 1, frag.name)
            script = cmds[0].split()[0]
            self.assertTrue(script.startswith('../'), frag.name)
            self.assertTrue((DASHBOARD / script).resolve().is_file(), f'{frag.name} -> {script}')
            if script != '../graphs.sh':
                for needle in ("s/&/\\&amp;/g", "s/</\\&lt;/g", "s/>/\\&gt;/g", "s/$/<br>/"):
                    self.assertIn(needle, cmds[0], frag.name)

    def test_index_sections_point_to_existing_fragments_and_every_script_has_one(self):
        index = (DASHBOARD / 'index.shtml').read_text(encoding='utf-8')
        frags = re.findall(r'data-frag="([^"]+)"', index)
        self.assertTrue(frags)
        for frag in frags:
            self.assertTrue((DASHBOARD / frag).is_file(), frag)
        used = set()
        for frag in DASHBOARD.glob('*.shtml'):
            for cmd in self.EXEC.findall(frag.read_text(encoding='utf-8')):
                used.add(cmd.split()[0].removeprefix('../'))
        self.assertEqual(sorted(used), SCRIPTS)

    def test_readme_lists_every_script(self):
        readme = (MUSE / 'README.md').read_text(encoding='utf-8')
        for name in SCRIPTS:
            self.assertIn(f'`{name}`', readme)


if __name__ == '__main__':
    unittest.main()
