#!/usr/bin/env python3
"""Fingerprint embed assets: CDN cache rules may ignore query strings."""
import hashlib
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]

def asset(name, source):
    path = Path(name)
    filename = f'{path.stem}-{hashlib.sha256(source.encode()).hexdigest()[:12]}{path.suffix}'
    (ROOT / 'chat' / filename).write_text(source)
    return filename

imports = {}
for name in ('socket.mjs', 'http-stream.mjs', 'session.mjs', 'markdown.mjs'):
    imports[name] = asset(name, (ROOT / 'chat' / name).read_text())
source = (ROOT / 'chat/app.mjs').read_text()
for name, filename in imports.items():
    source = re.sub(r'\./' + re.escape(name) + r'(?:\?[^\x27\x22]*)?', './' + filename, source)
script = asset('app.mjs', source)
style = asset('embed.css', (ROOT / 'chat/embed.css').read_text())
p = ROOT / 'conversation-embed.html'
s = re.sub(r'chat/app(?:-[0-9a-f]{12})?\.mjs(?:\?[^\x22]*)?', 'chat/' + script, p.read_text())
s = re.sub(r'chat/embed(?:-[0-9a-f]{12})?\.css(?:\?[^\x22]*)?', 'chat/' + style, s)
p.write_text(s)
print('Embed assets fingerprinted')
