#!/usr/bin/python3
"""Refresh a credential-free Cloudflare tunnel snapshot for unprivileged CGI."""
import json
from pathlib import Path
import subprocess
import time

path = Path('/var/cache/lib-api/tunnels.json')
path.parent.mkdir(parents=True, exist_ok=True)
while True:
    try:
        result = subprocess.run(['/usr/local/bin/cloudflared', 'tunnel', 'list', '--output', 'json'],
                                capture_output=True, timeout=20, check=True)
        rows = json.loads(result.stdout)
        sanitized = []
        for row in rows:
            connections = row.get('connections', [])
            sanitized.append({'id': row.get('id'), 'name': row.get('name'),
                'created_at': row.get('created_at'),
                'status': 'healthy' if connections else 'down',
                'connections': [{'colo_name': c.get('colo_name', '')} for c in connections]})
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(sanitized))
        tmp.chmod(0o644)
        tmp.replace(path)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    time.sleep(30)
