#!/usr/bin/python3
"""Private Unix-socket queue; fixed CLI invocations inside a read-only mount namespace."""
import grp
import json
import os
from pathlib import Path
import pwd
import queue
import re
import signal
import socket
import socketserver
import struct
import subprocess
import tempfile
import stat
import threading
import time
import uuid
from datetime import datetime, timezone

SOCKET = os.environ.get('LIB_CODEX_SOCKET', '/run/lib-codex/worker.sock')
STATE = Path(os.environ.get('LIB_LLM_STATE', '/var/lib/lib-llm/jobs'))
WORKSPACE = os.environ.get('LIB_LLM_WORKSPACE', '/app/lib')
HOME = '/var/lib/codex-web'
MAX_PROMPT = 16_384
MAX_OUTPUT = 32_768
TTL = 86_400
TIMEOUT = 300
IDS = re.compile(r'^(codex|claude)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
JOBS = queue.Queue(maxsize=8)
LOCK = threading.Lock()


def log_event(event):
    # Detached service stdout may no longer have a reader; logging must not
    # terminate the queue consumer.
    try:
        print(json.dumps(event), flush=True)
    except OSError:
        pass


def save(job):
    path = STATE / (job['ask_id'] + '.json')
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def lookup(ask_id):
    if not IDS.fullmatch(ask_id):
        return {'ask_error': 'invalid_ask_id', 'ask_status': 'failed'}
    path = STATE / (ask_id + '.json')
    try:
        if time.time() - path.stat().st_mtime > TTL:
            return {'ask_error': 'expired_ask_id', 'ask_status': 'failed'}
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {'ask_error': 'unknown_ask_id', 'ask_status': 'failed'}


def claude_authenticated():
    return any(Path(p).is_file() for p in (
        HOME + '/.claude/.credentials.json',
        HOME + '/.claude-api-key',
        HOME + '/.claude-oauth-token',
    ))


def submit(engine, prompt):
    if engine not in ('codex', 'claude'):
        return {'ask_error': 'unsupported_engine', 'ask_status': 'failed'}
    if not isinstance(prompt, str) or not prompt.strip():
        return {'ask_error': 'empty_prompt', 'ask_status': 'failed'}
    if len(prompt.encode()) > MAX_PROMPT:
        return {'ask_error': 'prompt_too_large', 'ask_status': 'failed'}
    if engine == 'claude' and not canonical_command(prompt).startswith('/') and not claude_authenticated():
        return {'ask_error': 'claude_not_authenticated', 'ask_status': 'failed', 'via': engine}
    job = {'ask_id': engine + '-' + str(uuid.uuid4()), 'ask_status': 'pending',
           'via': engine, 'created_at': time.time()}
    with LOCK:
        if JOBS.full():
            return {'ask_error': 'queue_full', 'ask_status': 'failed'}
        save(job)
        JOBS.put_nowait((job, prompt))
    return job


def command(engine, answer_path=None):
    user = pwd.getpwnam('codex-web')
    # root creates the namespace; the CLI and its tools run as codex-web.
    # Only the dedicated CLI home and temporary files are writable.
    args = ['/usr/bin/bwrap', '--ro-bind', '/', '/', '--bind', HOME, HOME,
            '--tmpfs', '/tmp', '--chmod', '1777', '/tmp',
            '--tmpfs', '/run', '--proc', '/proc', '--dev', '/dev',
            '--unshare-pid', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
            '--cap-add', 'CAP_SETUID', '--cap-add', 'CAP_SETGID', '--chdir', WORKSPACE,
            '--setenv', 'HOME', HOME, '--setenv', 'CODEX_HOME', HOME + '/.codex',
            '--setenv', 'PATH', '/opt/rbenv/versions/4.0.7/bin:/usr/local/bin:/usr/bin:/bin',
            '/usr/bin/setpriv', '--reuid', str(user.pw_uid), '--regid', str(user.pw_gid),
            '--clear-groups', '--no-new-privs']
    if engine == 'codex':
        args += ['/opt/codex-web/bin/codex', '-a', 'never', 'exec',
                 '--ignore-user-config', '--ignore-rules', '--ephemeral',
                 '--sandbox', 'danger-full-access', '--color', 'never',
                 '--skip-git-repo-check', '-']
        if answer_path:
            args += ['--output-last-message', answer_path]
    else:
        args += ['/usr/local/libexec/lib-claude-helper']
    return args


def run_bounded(args, prompt, timeout=TIMEOUT):
    # RLIMIT_FSIZE affects every file written by the CLI and its tools, including
    # databases and runtime artifacts. Bound only the captured output instead.
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    chunks = []
    overflow = threading.Event()

    def collect():
        size = 0
        while True:
            chunk = proc.stdout.read(65_536)
            if not chunk:
                break
            size += len(chunk)
            if size > 4_194_304:
                overflow.set()
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            chunks.append(chunk)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        try:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        raise TimeoutError
    finally:
        reader.join(timeout=2)
        proc.stdout.close()
    if overflow.is_set():
        raise OverflowError
    return proc.returncode, b''.join(chunks).decode('utf-8', errors='replace')


def failure_code(text, engine):
    """Return fixed diagnostic labels; never expose CLI text or credentials."""
    text = text.lower()
    if any(value in text for value in ('hit your usage limit', 'usage_limit_reached', 'insufficient_quota', 'rate_limit_exceeded')):
        return engine + '_usage_limit'
    if any(value in text for value in ('unauthorized', 'authentication', '401', 'token expired')):
        return engine + '_authentication_failed'
    if any(value in text for value in ('connection', 'reconnecting', 'network', 'stream disconnected')):
        return engine + '_connection_failed'
    if any(value in text for value in ('permission denied', 'read-only file system', 'operation not permitted')):
        return engine + '_permission_denied'
    return engine + '_execution_failed'


def save_failure_diagnostic(job, returncode, errors):
    directory = STATE.parent / 'diagnostics'
    directory.mkdir(mode=0o700, exist_ok=True)
    for old in directory.glob('*.json'):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink()
    path = directory / (job['ask_id'] + '.json')
    # Only CLI error events, never prompts, tool output, or final answers.
    record = {'exit_code': returncode, 'errors': errors[-8:]}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(record, output, ensure_ascii=False)


def codex_summary(text):
    metadata = {}
    # Native exec prints its configuration before the user prompt and tool output.
    for line in text.splitlines():
        if line.strip() in ('user', 'codex', 'thinking'):
            break
        match = re.fullmatch(r'(model|reasoning effort): ([a-zA-Z0-9_.:/-]+)', line)
        if match:
            metadata['model' if match[1] == 'model' else 'effort'] = match[2]
    return metadata


COMMAND_ALIASES = {'./usage': '/usage'}


def canonical_command(prompt):
    value = prompt.strip().lower()
    return COMMAND_ALIASES.get(value, value)


def control_command(argv):
    args = command('codex')
    return args[:args.index('/opt/codex-web/bin/codex')] + argv


def run_control(argv, truncate=True):
    code, text = run_bounded(control_command(argv), '', timeout=25)
    if code:
        raise ValueError('Control command failed')
    if truncate and len(text.encode()) > MAX_OUTPUT - 512:
        return text.encode()[:MAX_OUTPUT - 512].decode(errors='ignore') + '\n（表示上限で省略しました）'
    return text


DIFF_SCRIPT = r'''
import subprocess
base = ['git', '-c', 'safe.directory=' + __import__('os').getcwd(), '--no-pager']
def git(args, allowed=(0,)):
    p = subprocess.run(base + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if p.returncode not in allowed: raise SystemExit(2)
    return p.stdout
print('ステージ済み変更:')
print(git(['diff', '--no-ext-diff', '--no-textconv', '--cached']).decode(errors='replace'))
print('未ステージ変更:')
print(git(['diff', '--no-ext-diff', '--no-textconv']).decode(errors='replace'))
print('未追跡ファイル（gitignore 対象を除く）:')
for path in git(['ls-files', '--others', '--exclude-standard', '-z']).split(b'\0'):
    if path:
        print(git(['diff', '--no-ext-diff', '--no-textconv', '--no-index', '--', '/dev/null', path.decode()], (0, 1)).decode(errors='replace'))
'''


def read_codex_rpc(method, params=None, timeout=25):
    """Read account limits without starting a model turn, using the helper identity."""
    args = command('codex')
    args = args[:args.index('/opt/codex-web/bin/codex')] + [
        '/opt/codex-web/bin/codex', 'app-server', '--listen', 'stdio://']
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    responses = queue.Queue(maxsize=64)
    deadline = time.monotonic() + timeout

    def collect():
        while True:
            line = proc.stdout.readline(4_194_305)
            if len(line) > 4_194_304:
                # Directory update notifications can contain the entire catalog,
                # even when the requested response is paginated. Drain that
                # bounded frame and continue to the requested response.
                discarded = len(line)
                while line and not line.endswith(b'\n') and discarded <= 33_554_432:
                    line = proc.stdout.readline(4_194_305)
                    discarded += len(line)
                if discarded <= 33_554_432 and line.endswith(b'\n'):
                    continue
                responses.put(None)
                return
            if not line:
                responses.put(None)
                return
            try:
                responses.put_nowait(json.loads(line))
            except (ValueError, queue.Full):
                return

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()

    def send(message):
        proc.stdin.write((json.dumps(message) + '\n').encode())
        proc.stdin.flush()

    def receive(request_id):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                message = responses.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError
            if message is None:
                raise ValueError('Usage connection closed')
            if message.get('id') == request_id:
                if 'error' in message:
                    raise ValueError('Usage API unavailable')
                return message['result']

    try:
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'tunnels_usage', 'version': '1.0.0'}}})
        receive(1)
        send({'method': 'initialized', 'params': {}})
        request = {'id': 2, 'method': method}
        if params is not None:
            request['params'] = params
        send(request)
        return receive(2)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait(timeout=5)
        reader.join(timeout=2)
        proc.stdin.close()
        proc.stdout.close()


def read_codex_limits():
    return read_codex_rpc('account/rateLimits/read')


def format_codex_limits(data):
    buckets = data.get('rateLimitsByLimitId') or {}
    if not buckets and data.get('rateLimits'):
        buckets = {'codex': data['rateLimits']}
    lines = ['Codex 利用枠（アカウントの実データ）']
    count = 0
    for key, bucket in buckets.items():
        for label in ('primary', 'secondary'):
            window = bucket.get(label)
            if not window or window.get('usedPercent') is None:
                continue
            used = float(window['usedPercent'])
            remaining = max(0, min(100, 100 - used))
            minutes = window.get('windowDurationMins')
            period = f'{minutes / 60:g}時間枠' if minutes else label
            reset = window.get('resetsAt')
            reset_text = datetime.fromtimestamp(reset, timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if reset else '不明'
            lines.append(f'{key} {period}: 残り {remaining:g}%（使用 {used:g}%）、リセット {reset_text}')
            count += 1
    if not count:
        lines.append('この認証では利用枠が提供されていません。残り枠は不明です。')
    return '\n'.join(lines)


def codex_control_reply(prompt):
    command_name = canonical_command(prompt)
    if command_name in ('/mcp', '/mcp verbose'):
        data = read_codex_rpc('mcpServerStatus/list', {'limit': 100, 'detail': 'toolsAndAuthOnly'})
        lines = ['Codex /mcp — 連携用 Codex の MCP サーバー・ツール']
        for server in data.get('data', []):
            tools = server.get('tools') or {}
            lines.append(f'{server["name"]}: 認証 {server.get("authStatus", "不明")}, ツール {len(tools)}件')
            lines.extend('  ' + name for name in tools)
            if command_name.endswith(' verbose'):
                lines.append(f'  接続状態: {server.get("runtimeStatus") or "未取得"}')
                if server.get('toolsError'): lines.append('  ツール取得に失敗しました。')
        if not data.get('data'): lines.append('登録済みサーバーはありません。')
        if data.get('nextCursor'): lines.append('表示は最初の100件です。続きは対話型CLIで確認してください。')
        return '\n'.join(lines)
    if command_name == '/apps':
        installed = read_codex_rpc('app/installed', {'forceRefresh': False})
        try:
            data = read_codex_rpc('app/list', {'limit': 100, 'forceRefetch': False}, timeout=10)
            directory_unavailable = False
        except (OSError, ValueError, TimeoutError):
            data = {'data': []}
            directory_unavailable = True
        lines = ['Codex /apps — 利用可能なアプリ（連携用アカウント）']
        for app in installed.get('apps', []):
            lines.append(f'{app.get("runtimeName") or app["id"]}: 設定 {"有効" if app.get("enabled") else "無効"}, 呼出 {"可" if app.get("callable") else "不可"}')
        for app in data.get('data', []):
            lines.append(f'{app["name"]}: アクセス {"可" if app.get("isAccessible") else "不可"}, 設定 {"有効" if app.get("isEnabled", True) else "無効"}')
        if directory_unavailable: lines.append('アプリディレクトリの取得に失敗しました。上記は取得できたインストール済みアプリです。')
        elif not data.get('data') and not installed.get('apps'): lines.append('一覧にアプリはありません。')
        if data.get('nextCursor'): lines.append('表示は最初の100件です。続きは対話型CLIで確認してください。')
        lines.append('この表示ではアプリの選択・設定変更は行いません。')
        return '\n'.join(lines)
    if command_name == '/plugins':
        # Use the native CLI; plugin/list RPC is documented as under development.
        data = json.loads(run_control(['/opt/codex-web/bin/codex', 'plugin', 'list', '--available', '--json'], truncate=False))
        lines = ['Codex /plugins — インストール済み・利用可能なプラグイン']
        if isinstance(data, list): plugins = data
        else:
            plugins = data.get('plugins', []) + data.get('installed', []) + data.get('available', [])
            for marketplace in data.get('marketplaces', []): plugins.extend(marketplace.get('plugins', []))
        seen = set()
        for plugin in plugins:
            name = plugin.get('name') or plugin.get('id') or plugin.get('pluginId') or '名称不明'
            identity = plugin.get('pluginId') or name
            if identity in seen: continue
            seen.add(identity)
            lines.append(f'{name}: installed={plugin.get("installed", plugin.get("isInstalled", "不明"))}, enabled={plugin.get("enabled", plugin.get("isEnabled", "不明"))}')
        if not plugins: lines.append('一覧にプラグインはありません。')
        lines.append('この表示ではインストール・有効化の変更は行いません。')
        return '\n'.join(lines)
    if command_name == '/diff':
        return 'Codex /diff — 連携用作業ディレクトリの Git 差分\n' + run_control(['/usr/bin/python3', '-c', DIFF_SCRIPT])
    if command_name == '/ps':
        return ('Codex /ps — バックグラウンド端末\n'
                'この連携は独立した CLI ジョブを実行するため、対話セッションの端末状態は取得できません。\n'
                '端末が0件とは判断しません。既存セッションの /ps で確認してください。\n'
                'VM 全体のプロセス一覧で代用しません。')
    if command_name == '/usage':
        return ('Codex /usage — アカウントのトークン使用量\n'
                '/usage daily: 日別\n/usage weekly: 週別\n/usage cumulative: 累計\n'
                'TUI の使用量メニューに相当します。利用枠は /status で確認できます。\n'
                '利用枠リセットの対話操作はこの連携では未対応です。')
    if command_name.startswith('/usage '):
        view = command_name.split(maxsplit=1)[1]
        if view not in ('daily', 'weekly', 'cumulative'):
            return 'Codex /usage: daily・weekly・cumulative を指定してください。その他の操作は連携未対応です。'
        data = read_codex_rpc('account/usage/read')
        lines = [f'Codex /usage {view} — アカウントのトークン使用量']
        if view == 'cumulative':
            summary = data.get('summary') or {}
            for field, label in [('lifetimeTokens', '累計トークン'), ('peakDailyTokens', '最大日別トークン'), ('currentStreakDays', '連続利用日数'), ('longestStreakDays', '最長連続利用日数'), ('longestRunningTurnSec', '最長ターン秒数')]:
                value = summary.get(field)
                lines.append(f'{label}: {value if value is not None else "不明"}')
        else:
            buckets = data.get('dailyUsageBuckets')
            if buckets is None:
                lines.append('トークン使用量は提供されていません（不明）。')
            elif not buckets:
                lines.append('返却された日別使用量データはありません。')
            elif view == 'daily':
                for bucket in buckets:
                    lines.append(f'{bucket["startDate"]}: {bucket["tokens"]} tokens')
            else:
                totals = {}
                for bucket in buckets:
                    date = datetime.fromisoformat(bucket['startDate'])
                    iso = date.isocalendar()
                    key = f'{iso.year}-W{iso.week:02d}'
                    totals[key] = totals.get(key, 0) + bucket['tokens']
                lines.append('API の日別データを ISO 週で集計（取得できた期間のみ）。')
                lines.extend(f'{key}: {total} tokens' for key, total in sorted(totals.items()))
        return '\n'.join(lines)
    if command_name == '/status':
        config = read_codex_rpc('config/read', {'includeLayers': False, 'cwd': WORKSPACE}).get('config') or {}
        lines = ['Codex /status — 連携用 Codex の設定・状態', f'作業ディレクトリ: {WORKSPACE}']
        for field, label in [('model', 'モデル設定'), ('model_reasoning_effort', '推論設定'), ('model_context_window', 'コンテキスト上限設定')]:
            value = config.get(field)
            lines.append(f'{label}: {value if value is not None else "未指定（既定値）"}')
        lines.extend(['通常実行の承認ポリシー: never', '通常実行のサンドボックス: 読み取り専用マウント内で danger-full-access',
                      '既存の対話セッションには接続していません。セッションID・使用トークン・残りコンテキストは取得対象外です。'])
        lines.append(format_codex_limits(read_codex_limits()))
        return '\n'.join(lines)
    return 'このスラッシュコマンドは連携未対応です。対話型 Codex CLI で実行してください。通常のAI質問には変換しません。'


def execute_codex(prompt):
    if canonical_command(prompt).startswith('/'):
        try:
            return 0, '', codex_control_reply(prompt)
        except (OSError, ValueError, KeyError, TypeError, TimeoutError, subprocess.TimeoutExpired):
            missing = '残り枠は不明' if canonical_command(prompt) == '/status' else '取得できない情報は不明'
            return 0, '', f'Codex のコマンド情報を取得できませんでした。認証状態・接続を確認して再試行してください（{missing}）。'
    user = pwd.getpwnam('codex-web')
    with tempfile.TemporaryDirectory(prefix='.llm-answer-', dir=HOME) as directory:
        os.chown(directory, user.pw_uid, user.pw_gid)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            code, text = run_bounded(command('codex', directory + '/answer'), prompt)
            try:
                fd = os.open('answer', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            except FileNotFoundError:
                return code, text, None
            with os.fdopen(fd, 'rb') as answer:
                info = os.fstat(answer.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != user.pw_uid:
                    raise ValueError('Invalid answer file')
                reply = answer.read(MAX_OUTPUT).decode('utf-8', errors='ignore')
            return code, text, reply
        finally:
            os.close(directory_fd)


CLAUDE_RESUME_SCRIPT = r'''
import json, os, re
from pathlib import Path
from datetime import datetime, timezone

root = Path(os.environ['HOME']) / '.claude/projects'
sessions = []
scanned = 0
limited = False
if root.is_dir():
    for project_index, project in enumerate(root.iterdir()):
        if project_index >= 1000:
            limited = True
            break
        if project.is_symlink() or not project.is_dir():
            continue
        for path in project.iterdir():
            if scanned >= 2000:
                limited = True
                break
            scanned += 1
            if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.jsonl', path.name):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            try:
                info = path.stat()
                with path.open('rb') as stream:
                    # Only inspect bounded metadata, never return message bodies.
                    prefix = stream.read(65536)
                cwd = None
                for line in prefix.splitlines()[:40]:
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if (event.get('type') == 'user' and not event.get('isSidechain')
                            and event.get('sessionId') == path.stem
                            and isinstance(event.get('cwd'), str)):
                        cwd = event['cwd']
                        break
                if cwd:
                    sessions.append((info.st_mtime, path.stem, cwd))
            except OSError:
                continue
        if limited:
            break
print('Claude /resume — codex-web の保存済み再開候補（更新日時順・最大20件）')
for modified, session, cwd in sorted(sessions, reverse=True)[:20]:
    date = datetime.fromtimestamp(modified, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f'{session} | {date} | {json.dumps(cwd, ensure_ascii=False)}')
if not sessions:
    print('保存済みの再開候補は見つかりませんでした。')
if limited or len(sessions) > 20:
    print('件数上限のため一部のみ表示しています。')
print('この表示では再開・送信は行いません。再開には対話型 CLI で claude --resume <ID> を使います。')
print('通常の連携ジョブは --no-session-persistence のため、この一覧には保存されません。')
'''


def execute_claude_control(prompt):
    name = canonical_command(prompt)
    if name == '/permission':
        name = '/permissions'
    if name not in ('/cost', '/mcp', '/model', '/agents', '/context', '/config', '/hooks', '/resume', '/help', '/permissions', '/status'):
        return 0, '', 'Claude のスラッシュコマンドはこの連携では未対応です。Claude Code の対話画面で実行してください。Codex の情報で代用しません。'
    if name == '/resume':
        return 0, '', run_control(['/usr/bin/python3', '-c', CLAUDE_RESUME_SCRIPT])
    if name == '/help':
        return 0, '', ('Claude 連携ヘルプ\n\n'
                       '/cost：利用状況・リセット時刻\n'
                       '/status：CLIバージョン・モデル・実行環境\n'
                       '/model：現在のモデル\n'
                       '/context：今回の連携セッションのコンテキスト使用状況\n'
                       '/mcp：連携用MCPの接続状況\n'
                       '/agents：サブエージェントの管理方法\n'
                       '/hooks：hooksの無効状態・ユーザー登録状況\n'
                       '/permissions：権限設定（/permission も可）\n'
                       '/config：設定コマンドの使い方\n'
                       '/resume：保存済みセッションの再開候補一覧\n'
                       '/help：この一覧\n\n'
                       '呼び出し例：claude_prompt="/status"\n'
                       '引数なしの情報表示のみ対応。設定変更・会話の再開は行いません。')
    # Dialog-only commands use actual initialization data from a local /model.
    native = '/model' if name in ('/permissions', '/status', '/hooks') else name
    code, text = run_bounded(command('claude'), native)
    if code != 0:
        return code, '', None
    init = {}
    result = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            init = event
        if (event.get('type') == 'result' and event.get('local_command') == native[1:]
                and event.get('num_turns') == 0 and not event.get('is_error')
                and isinstance(event.get('result'), str) and event['result'].strip()):
            result = event['result']
    if result is not None:
        if name == '/context':
            result = ('このリクエストで新規起動した連携セッションのコンテキストです。'
                      '既存の対話セッションや過去ジョブの累積使用量ではありません。\n\n' + result)
        elif name == '/config':
            result = ('CLI の設定コマンドの使い方（引数なし）。'
                      'この連携では設定変更は行いません。\n\n' + result)
        elif name == '/hooks':
            if not init:
                return 1, '', None
            path = Path(HOME) / '.claude/settings.json'
            settings = json.loads(path.read_text()) if path.is_file() else {}
            hooks = settings.get('hooks', {})
            if not isinstance(hooks, dict):
                raise ValueError('Invalid hooks settings')
            lines = ['連携ヘルパーの実効設定: disableAllHooks=true（hooks は無効）',
                     'ユーザー設定に登録されたイベント別の設定数（実行しません）:']
            for event_name, entries in sorted(hooks.items()):
                count = len(entries) if isinstance(entries, list) else '不明'
                lines.append(f'{event_name}: {count}')
            if not hooks:
                lines.append('ユーザー設定に hooks の登録はありません。')
            lines.append('ユーザー設定のみを対象とし、プロジェクト・プラグイン等の hooks 一覧ではありません。')
            lines.append('このコマンドは情報表示のみで、hooks の登録・有効化・実行は行いません。')
            result = '\n'.join(lines)
        elif name == '/status':
            if not init:
                return 1, '', None
            lines = ['CLI 起動情報（独立した連携ジョブ）']
            for key, label in [('claude_code_version', 'CLI バージョン'), ('model', 'モデル'), ('permissionMode', '承認モード'), ('cwd', '作業ディレクトリ')]:
                lines.append(f'{label}: {init.get(key, "不明")}')
            lines.append('MCP: ' + json.dumps(init.get('mcp_servers', []), ensure_ascii=False))
            lines.append('既存の対話セッションの状態・コンテキスト使用量は取得対象外です。')
            result = '\n'.join(lines)
        elif name == '/permissions':
            if not init:
                return 1, '', None
            path = Path(HOME) / '.claude/settings.json'
            settings = json.loads(path.read_text()) if path.is_file() else {}
            result = (f'実際の承認モード: {init.get("permissionMode", "不明")}\n'
                      '連携ヘルパー: hooks 無効、ユーザー設定のみ読込、MCP 設定は空に固定。\n'
                      '許可ツール指定: Read,Grep,Glob,Bash,WebSearch,WebFetch\n'
                      'ユーザー権限設定:\n' + json.dumps(settings.get('permissions', {}), ensure_ascii=False, indent=2) +
                      '\nユーザーの sandbox 設定:\n' + json.dumps(settings.get('sandbox', {}), ensure_ascii=False, indent=2) +
                      '\n承認が必要な未許可操作は dontAsk により拒否されます。OS の読み取り専用マウントも適用されます。\n'
                      'このコマンドは情報表示のみで、権限を変更しません。')
        return 0, '', f'Claude {name} — 連携用 CLI 実データ\n' + result
    # Never substitute an assistant response or fabricate a zero-cost total.
    return 1, '', None


def execute(job, prompt):
    job.update(ask_status='running', started_at=time.time())
    save(job)
    try:
        # The prompt is stdin, never a shell command or CLI option.
        if job['via'] == 'claude' and canonical_command(prompt).startswith('/'):
            returncode, text, reply = execute_claude_control(prompt)
        elif job['via'] == 'codex':
            returncode, text, reply = execute_codex(prompt)
            job.update(codex_summary(text))
        else:
            returncode, text = run_bounded(command(job['via']), prompt)
            reply = None
            job['effort'] = 'high'
        error = None
        diagnostic = ''
        errors = []
        for line in text.splitlines():
            if job['via'] == 'codex':
                if line.startswith('ERROR:'):
                    diagnostic = line
                    errors.append({'type': 'cli_error', 'detail': line[:4096]})
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'system' and event.get('subtype') == 'init':
                model = event.get('model', '')
                if isinstance(model, str) and re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,128}', model):
                    job['model'] = model
            elif event.get('type') == 'assistant' and not event.get('parent_tool_use_id'):
                model = (event.get('message') or {}).get('model', '')
                if isinstance(model, str) and re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,128}', model):
                    job['model'] = model
            elif event.get('type') == 'result':
                reply = event.get('result')
                if event.get('is_error'):
                    error = 'claude_execution_failed'
        if returncode != 0 or error or not reply:
            job.update(ask_status='failed', ask_error=error or failure_code(diagnostic, job['via']))
            save_failure_diagnostic(job, returncode, errors)
        else:
            job.update(ask_status='done', reply=reply.encode()[:MAX_OUTPUT].decode('utf-8', errors='ignore'))
    except TimeoutError:
        job.update(ask_status='failed', ask_error='llm_timeout')
    except OverflowError:
        job.update(ask_status='failed', ask_error='llm_output_limit')
    except (OSError, ValueError):
        job.update(ask_status='failed', ask_error='llm_helper_failed')
    job['finished_at'] = time.time()
    if job.get('model'):
        job['llm_model'] = job['model']
    if job.get('effort'):
        job['llm_effort'] = job['effort']
    save(job)
    log_event({'ask_id': job['ask_id'], 'status': job['ask_status']})


def consume():
    while True:
        job, prompt = JOBS.get()
        try:
            execute(job, prompt)
        except Exception as error:
            # Keep accepting later jobs even if a helper or result parser fails.
            job.update(ask_status='failed', ask_error='worker_job_failed', finished_at=time.time())
            try:
                save(job)
            except OSError:
                pass
            log_event({'ask_id': job['ask_id'], 'status': 'failed',
                       'error_type': type(error).__name__})
        finally:
            JOBS.task_done()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        _, uid, _ = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in (0, pwd.getpwnam('www-data').pw_uid):
            return
        try:
            line = self.rfile.readline(32_769)
            if len(line) > 32_768:
                raise ValueError
            req = json.loads(line)
            if req.get('op') == 'submit':
                result = submit(req.get('engine'), req.get('prompt'))
            elif req.get('op') == 'poll':
                result = lookup(str(req.get('ask_id', '')))
            else:
                result = {'ask_error': 'invalid_operation'}
        except (ValueError, OSError):
            result = {'ask_error': 'invalid_request'}
        self.wfile.write((json.dumps(result, ensure_ascii=False) + '\n').encode())


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    if os.getuid() != 0:
        raise SystemExit('Run worker as root; helpers drop to codex-web in a read-only namespace.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in STATE.glob('*.json'):
        if time.time() - path.stat().st_mtime > TTL:
            path.unlink()
            continue
        job = json.loads(path.read_text())
        if job.get('ask_status') in ('pending', 'running'):
            job.update(ask_status='failed', ask_error='worker_restarted')
            save(job)
    path = Path(SOCKET)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(SOCKET)
            raise SystemExit('Worker already running')
        except ConnectionRefusedError:
            path.unlink()
        finally:
            probe.close()
    server = Server(SOCKET, Handler)
    os.chown(SOCKET, 0, grp.getgrnam('www-data').gr_gid)
    os.chmod(SOCKET, 0o660)
    threading.Thread(target=consume, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
