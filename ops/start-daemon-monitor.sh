#!/bin/bash
# Start one read-only snapshot collector. Run detached as root.
set -euo pipefail
install -d -m 0755 /run/lock
exec 9>/run/lock/lib-daemon-snapshot.lock
flock -n 9 || exit 0
exec /usr/bin/python3 /app/lib/ops/daemon_snapshot.py
