#!/usr/bin/env python3
"""Read-only daemon probes; publish a sanitized, atomic snapshot for CGI."""
import argparse
import concurrent.futures
import datetime
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import time
import urllib.request

CACHE = Path('/var/cache/lib-api/daemons.json')
SERVICES = [
    ('apache', 'Apache', 'apache2', None, 'tls', 8443, 'Web オリジン'),
    ('caddy', 'Caddy', 'caddy', '/app/web-proxy/Caddyfile', 'tls', 9443, 'Web リバースプロキシ'),
    ('postgres', 'PostgreSQL', 'postgres', None, 'postgres', 5432, 'データベース'),
    ('cloudflared', 'Cloudflare Tunnel', 'cloudflared', None, 'http', 20241, '公開トンネル'),
    ('docker', 'Docker', 'dockerd', None, 'docker', None, 'コンテナ管理'),
    ('containerd', 'containerd', 'containerd', None, 'unix', '/var/run/docker/containerd/containerd.sock', 'コンテナランタイム'),
    ('ssh', 'SSH', 'sshd', None, 'ssh', 22, 'SSH 接続'),
    ('llm-worker', 'LLM worker', 'python3', '/usr/local/libexec/lib-llm-worker.py', 'unix', '/run/lib-codex/worker.sock', 'Codex / Claude ジョブ'),
    ('tunnel-cache', 'Tunnel cache', 'python3', '/usr/local/libexec/lib-tunnel-cache.py', 'cache', '/var/cache/lib-api/tunnels.json', 'トンネル情報の収集'),
    ('railway-agent', 'Railway Agent', 'railway-agent', None, 'tcp', 8787, 'Railway チャット'),
    ('express-agent', 'Cloud Agent', 'express-agent', 'serve', 'process', None, 'VM のエージェント'),
    ('daemon-snapshot', '稼働データ収集', 'python3', 'daemon_snapshot.py', 'process', None, 'この画面のデータ収集'),
]


def processes():
    rows = []
    ticks = os.sysconf('SC_CLK_TCK')
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    for path in Path('/proc').glob('[0-9]*'):
        try:
            comm = (path / 'comm').read_text().strip()
            argv = (path / 'cmdline').read_bytes().decode(errors='replace').split('\0')
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] == 'Z':
                continue
            age = max(0, int(uptime - int(fields[19]) / ticks))
            rows.append({'pid': int(path.name), 'comm': comm, 'argv': argv, 'age': age})
        except (OSError, ValueError, IndexError):
            continue
    return rows


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


def docker_data():
    conn = UnixHTTP('localhost', timeout=2)
    try:
        conn.request('GET', '/_ping')
        response = conn.getresponse()
        body = response.read(1024)
        if response.status != 200 or body != b'OK':
            raise OSError('Docker ping failed')
        conn.request('GET', '/containers/json?all=true')
        response = conn.getresponse()
        if response.status != 200:
            raise OSError('Docker list failed')
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Docker response too large')
        rows = json.loads(raw)
        containers = [{'name': ', '.join(n.lstrip('/') for n in row.get('Names', [])),
                       'image': row.get('Image', ''), 'state': row.get('State', ''),
                       'status': row.get('Status', '')} for row in rows]
        return containers
    finally:
        conn.close()


def probe(kind, target):
    if kind == 'process':
        return 'プロセス稼働（応答テストなし）', None
    if kind == 'docker':
        containers = docker_data()
        return f'Docker API 応答 · コンテナ {len(containers)} 件', containers
    if kind == 'cache':
        age = max(0, int(time.time() - Path(target).stat().st_mtime))
        json.loads(Path(target).read_text())
        if age > 120:
            raise ValueError(f'キャッシュが古い（{age}秒前）')
        return f'キャッシュ更新 {age} 秒前', None
    if kind in ('tls', 'http'):
        url = f'https://localhost:{target}/lib/date.shtml' if kind == 'tls' else f'http://127.0.0.1:{target}/ready'
        context = ssl.create_default_context(cafile='/etc/apache2/tls/origin-ca.crt') if kind == 'tls' else None
        with urllib.request.urlopen(url, timeout=2, context=context) as response:
            response.read(1024)
            return f'HTTP {response.status} 応答', None
    if kind == 'unix':
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(2)
            conn.connect(target)
        return 'Unix ソケット接続成功（処理結果は未検査）', None
    with socket.create_connection(('127.0.0.1', target), timeout=2) as conn:
        if kind == 'ssh':
            if not conn.recv(256).startswith(b'SSH-'):
                raise ValueError('SSH バナー不正')
            return 'SSH 応答', None
        if kind == 'postgres':
            conn.sendall(b'\x00\x00\x00\x08\x04\xd2\x16\x2f')
            if conn.recv(1) not in (b'S', b'N'):
                raise ValueError('PostgreSQL 応答不正')
            return 'PostgreSQL プロトコル応答（SQL 未実行）', None
    return 'TCP 接続成功（アプリ応答は未検査）', None


def check_service(spec, rows):
    key, name, comm, needle, kind, target, purpose = spec
    matches = [row for row in rows if row['comm'] == comm and
               (needle is None or any(needle == arg or (needle == 'daemon_snapshot.py' and arg.endswith('/daemon_snapshot.py')) for arg in row['argv']))]
    result = {'key': key, 'name': name, 'purpose': purpose,
              'pids': sorted(row['pid'] for row in matches), 'process_count': len(matches),
              'uptime_seconds': max((row['age'] for row in matches), default=None),
              'probe': kind, 'state': 'stopped', 'detail': 'プロセスなし'}
    if not matches:
        return result
    started = time.monotonic()
    try:
        detail, containers = probe(kind, target)
        result.update(state='running', detail=detail)
        if containers is not None:
            result['containers'] = containers
    except PermissionError:
        result.update(state='unknown', detail='プロセスあり · 応答確認の権限なし')
    except (OSError, ValueError, http.client.HTTPException) as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        result.update(state='degraded', detail=f'プロセスあり · 応答確認失敗: {detail}')
    result['latency_ms'] = round((time.monotonic() - started) * 1000)
    return result


def resources():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key] = int(value.split()[0]) * 1024
    disk = os.statvfs('/app')
    return {'memory_total_bytes': memory['MemTotal'], 'memory_available_bytes': memory['MemAvailable'],
            'swap_used_bytes': memory['SwapTotal'] - memory['SwapFree'],
            'disk_total_bytes': disk.f_blocks * disk.f_frsize,
            'disk_available_bytes': disk.f_bavail * disk.f_frsize,
            'load_average': list(os.getloadavg()),
            'uptime_seconds': int(float(Path('/proc/uptime').read_text().split()[0]))}


def snapshot():
    rows = processes()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        services = list(pool.map(lambda spec: check_service(spec, rows), SERVICES))
    return {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'interval_seconds': 15, 'scope': 'この Railway VM',
            'resources': resources(), 'services': services}


def publish(data):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=CACHE.parent, delete=False) as out:
        json.dump(data, out, ensure_ascii=False)
        path = Path(out.name)
    path.chmod(0o644)
    path.replace(CACHE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            publish(snapshot())
        except Exception as error:
            print(f'snapshot failed: {type(error).__name__}', flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(15)


if __name__ == '__main__':
    main()
