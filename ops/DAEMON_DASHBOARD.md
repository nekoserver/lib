# Railway VM daemon dashboard

Page: `/lib/dashboard/railway/` (the path without the trailing slash redirects).
JSON: `GET /lib/dashboard/railway/status.rb`.

The JSON endpoint uses existing HmacAuth IP allowlist / verified Access / HMAC
checks. The HTML shell and static assets contain no operational data. Browsers
outside the allowlist can enter the existing HMAC key; it is kept in page memory,
not storage, and cleared from the input after connecting. The actual GET path
is signed on each request. No keys or process command lines are in snapshots.

The collector performs read-only, bounded probes every 15 seconds. Run as root
so it can read Docker's Unix socket; CGI never gets Docker socket access.

```sh
setsid -f /app/lib/ops/start-daemon-monitor.sh >/var/log/lib-daemon-snapshot.log 2>&1
```

The startup script uses flock to prevent duplicate collectors. On this VM,
`/app/start-web.sh` also starts this collector after wake. For another host,
add the above invocation to that host's startup mechanism. Processes do not
survive VM sleep; files and configuration do.

Snapshot: `/var/cache/lib-api/daemons.json`, written atomically, mode 0644.
The endpoint can override this path with `LIB_DAEMON_CACHE`. It reports an age
and marks data older than 60 seconds stale. Missing or corrupt snapshots return
503. Stale data is displayed with a warning, never presented as current.

Checks cover Apache, origin Caddy, PostgreSQL, Cloudflare Tunnel, Docker,
containerd, SSH, LLM worker, tunnel cache, Railway Agent, Cloud Agent, and the
collector itself. Process existence, HTTP readiness, protocol responses, TCP
connections, and Unix socket connections are explicitly distinguished. Checks
do not prove SQL queries, LLM jobs, or other business operations succeed.
Docker's sanitized container list includes names, images, state and status;
no image environment, credentials or mounts are emitted. The dashboard is
read-only and cannot start, stop or restart daemons.

Validation:

```sh
python3 test/daemon_snapshot_test.py
python3 ops/daemon_snapshot.py --once
node --check dashboard/railway/dashboard.js
```
