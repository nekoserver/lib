#!/bin/sh
# 設定済み配布元の候補とインストール済みの版を表示する。
set -u
exec python3 - <<'PY'
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def query(*command):
    try:
        result = subprocess.run(
            command, env={**os.environ, 'LC_ALL': 'C'}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return result.stdout if result.returncode == 0 else ''


def nix_versions():
    home = Path.home()
    local_nix = home / 'bin/nix-env'
    nix = str(local_nix) if os.access(local_nix, os.X_OK) else shutil.which('nix-env')
    compared = {}
    if nix:
        for line in query(nix, '-q', '--compare-versions').splitlines():
            row = re.fullmatch(r'(\S+)\s+[<=>-]\s+(\S+)', line)
            if row:
                compared[row[1]] = row[2] if row[2] != '?' else None
    manifest = home / '.nix-profile/manifest.json'
    if manifest.is_file():
        try:
            elements = json.loads(manifest.read_text(encoding='utf-8'))['elements']
            if isinstance(elements, dict):
                elements = elements.values()
            for element in elements:
                if not isinstance(element, dict):
                    continue
                for store_path in element.get('storePaths', []):
                    name = Path(store_path).name.partition('-')[2]
                    if name:
                        compared.setdefault(name, None)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    elif not compared and nix:
        compared = dict.fromkeys(query(nix, '-q').splitlines())
    for package, candidate in sorted(compared.items()):
        parts = re.fullmatch(r'(.+?)-([0-9]\S*)', package)
        yield (parts[1], parts[2], candidate) if parts else (package, '未確認', candidate)


def apt_candidates(packages):
    if not packages:
        return {}
    candidates = {}
    # Installed-only entries also appear as Candidate in APT. Confirm that the
    # candidate is listed in a configured package index before calling it current.
    policy = query('apt-cache', 'policy', *packages)
    package = candidate = version = None
    for line in policy.splitlines():
        if line and not line[0].isspace() and line.endswith(':'):
            package, candidate, version = line[:-1], None, None
        elif line.lstrip().startswith('Candidate: '):
            candidate = line.split('Candidate: ', 1)[1]
        elif match := re.fullmatch(r'\s*(?:\*\*\*\s+)?(\S+)\s+-?\d+\s*', line):
            version = match[1]
        elif candidate and version == candidate and line.strip().endswith(' Packages'):
            candidates[package] = candidate
    return candidates


def deb_versions():
    installed = {}
    for line in query('dpkg-query', '-W', '-f=${db:Status-Abbrev}\\t${binary:Package}\\t${Version}\\n').splitlines():
        fields = line.split('\t')
        if len(fields) == 3 and fields[0][1:2] == 'i':
            installed[fields[1]] = fields[2]
    available = apt_candidates(installed)
    for package, version in sorted(installed.items()):
        yield package, version, available.get(package)


for label, rows in (
    ('Nix プロファイル（設定済みの Nix 式）', nix_versions()),
    ('.deb（設定済みの APT 索引）', deb_versions()),
):
    print(f'== {label} ==')
    print('パッケージ\tインストール済み\t最新版候補')
    for package, installed, candidate in rows:
        print(package, installed, candidate or '未確認', sep='\t')
    print()
PY
