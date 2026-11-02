#!/usr/bin/env python3
"""Stream endpoints of this container, derived from its Cloudflare Tunnel ingress.

Which public hostname reaches this container depends on the tunnel it was started
with (entrypoint.sh renders /etc/cloudflared/ingress.yml from NEKOROOT_HOSTNAME).
The embed page connects to its own origin, so the stream servers must accept that
origin (LIB_CHAT_ORIGINS) and the main Worker must list it as a stream route
(src/data/conversation-stream-routes.json there, validated by
src/utils/conversationStreamRoutes.ts). This derives both from the ingress.

    stream_routes.py env    [--ingress PATH]            # LIB_CHAT_ORIGINS=... (keeps existing values)
    stream_routes.py worker [--ingress PATH] --id ID    # route entries for the Worker ledger (JSON)
    stream_routes.py endpoints [--ingress PATH]         # embed / websocket / sse / ndjson / jsonseq URLs
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit

INGRESS = Path('/etc/cloudflared/ingress.yml')
# The Apache front (TLS 8443) serves /lib/conversation-embed.html and proxies /lib/api/chat/*.
STREAM_SERVICES = re.compile(r'^https://(?:127\.0\.0\.1|localhost):8443/?$')
HOSTNAME = re.compile(r'^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')
ROUTE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,31}$')
PATHS = {'embed': '/lib/conversation-embed.html', 'websocket': '/lib/api/chat/ws',
         'sse': '/lib/api/chat/sse', 'ndjson': '/lib/api/chat/ndjson', 'jsonseq': '/lib/api/chat/jsonseq'}


def _scalar(value):
    value = re.sub(r'\s+#.*$', '', value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        value = value[1:-1]
    return value


def ingress_rules(path=INGRESS):
    """The top-level `ingress:` list as dicts of scalar keys (hostname/path/service)."""
    rules, current, inside, item_indent = [], None, False, None
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            inside = line.split(':', 1)[0].strip() == 'ingress'
            continue
        if not inside:
            continue
        text = line.strip()
        if text.startswith('- '):
            item_indent = indent
            current = {}
            rules.append(current)
            text = text[2:]
        elif current is None or indent <= item_indent:
            continue
        elif indent > item_indent + 2:
            continue  # nested mapping such as originRequest
        key, _, value = text.partition(':')
        if value.strip():
            current[key.strip()] = _scalar(value)
    return rules


def stream_hostnames(path=INGRESS):
    hosts = []
    for rule in ingress_rules(path):
        host = rule.get('hostname', '').lower()
        if not host or rule.get('path') or not STREAM_SERVICES.match(rule.get('service', '')):
            continue
        if not HOSTNAME.match(host):
            raise ValueError(f'Ingress hostname is not a rendered DNS name: {host}')
        if host not in hosts:
            hosts.append(host)
    return hosts


def endpoints(origin):
    parts = urlsplit(origin)
    if parts.scheme != 'https' or not parts.hostname or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username:
        raise ValueError(f'Not a bare HTTPS origin: {origin}')
    host = parts.netloc
    return {name: ('wss' if name == 'websocket' else 'https') + '://' + host + path for name, path in PATHS.items()}


def chat_origins(hosts, existing=''):
    origins = [value.strip() for value in existing.split(',') if value.strip()]
    for host in hosts:
        if 'https://' + host not in origins:
            origins.append('https://' + host)
    return ','.join(origins)


def worker_routes(hosts, route_id):
    if not ROUTE_ID.match(route_id) or route_id == 'auto':
        raise ValueError(f'Route id must be lowercase letters, digits and hyphens: {route_id}')
    return [{'id': route_id if index == 0 else f'{route_id}-{index + 1}', 'origin': 'https://' + host}
            for index, host in enumerate(hosts)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=('env', 'worker', 'endpoints'))
    parser.add_argument('--ingress', default=str(INGRESS))
    parser.add_argument('--id', help='route id for the Worker ledger (worker command)')
    args = parser.parse_args(argv)
    hosts = stream_hostnames(args.ingress)
    if not hosts:
        raise SystemExit(f'No hostname in {args.ingress} routes to the stream server (8443)')
    if args.command == 'env':
        print('LIB_CHAT_ORIGINS=' + shlex.quote(chat_origins(hosts, os.environ.get('LIB_CHAT_ORIGINS', ''))))
    elif args.command == 'worker':
        if not args.id:
            parser.error('worker needs --id')
        print(json.dumps(worker_routes(hosts, args.id), ensure_ascii=False))
    else:
        print(json.dumps({host: endpoints('https://' + host) for host in hosts}, indent=2))


if __name__ == '__main__':
    main()
