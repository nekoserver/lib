#!/bin/sh
# Restore the lib/claude services on a freshly started cf-container (run as root from any directory):
#   1. copy lib/api, lib/claude/api, lib/ops, lib/chat and conversation-embed.html to
#      /var/www/html/lib (www-data cannot traverse /root)
#   2. write /etc/apache2/lib-secrets.conf (0600) from ORIGIN_HMAC_SECRET and the Cloudflare token
#   3. route /lib/api/tunnels to tunnels.claude.rb, and the AI chat embed page and streams
#      to the stream servers, instead of server.js; then start or reload Apache and check port 8443
#      (and on the image's internal vhost 127.0.0.1:8445, relay the conversation stream for tree-view's
#      worker tab unless the image already does)
#   4. start the LLM worker, the chat observer and the chat stream servers, replacing the
#      original worker and observer that the demo image starts on the same sockets
#   5. restore the main Worker repo's Claude Code hooks after the container start (restore-claude-hooks.sh):
#      check the hook scripts, and copy the guards that work in any directory (full test, Japanese,
#      self check) into ~/.claude/settings.json, so a session started in /root has them too
#
# Token: LIB_TUNNELS_CF_TOKEN, else CF_CONTAINER_API_TOKEN of the caller. The token that
# entrypoint.sh hands Apache (/etc/profile.d/cf-env.sh) lists no tunnels, so it is not used.
# LIB_ROUTE_ACCESS_CONTROL=1 (startup option from the main Worker) turns on route-based access control.
# Paths can be overridden for tests: LIB_WWW, LIB_APACHE_DIR, LIB_APACHE_SITE.
# LIB_RESTORE_NO_START=1 skips the Apache reload and the daemons.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
LIB=$(cd "$HERE/../.." && pwd)
WWW=${LIB_WWW:-/var/www/html/lib}
APACHE=${LIB_APACHE_DIR:-/etc/apache2}
SITE=${LIB_APACHE_SITE:-$APACHE/sites-available/000-demo.conf}
SECRET=${ORIGIN_HMAC_SECRET:-${HMAC_SECRET:-}}
TOKEN=${LIB_TUNNELS_CF_TOKEN:-${CF_CONTAINER_API_TOKEN:-}}
[ -n "$SECRET" ] || { echo "Set ORIGIN_HMAC_SECRET" >&2; exit 1; }
[ -n "$TOKEN" ] || { echo "Set LIB_TUNNELS_CF_TOKEN or CF_CONTAINER_API_TOKEN" >&2; exit 1; }

# The main image's entrypoint bind-mounts /root/lib on /var/www/html/lib (lib-restore-wait.sh); then the files are
# already there, and copying lib onto itself fails with "are the same file".
if [ -d "$WWW" ] && [ "$LIB" -ef "$WWW" ]; then
  echo "lib: $WWW is the lib checkout itself (bind mount), nothing to copy"
else
  install -d -m 0755 "$WWW/api" "$WWW/claude/api" "$WWW/ops" "$WWW/chat"
  cp -a "$LIB/api/." "$WWW/api/"
  cp -a "$LIB/claude/api/." "$WWW/claude/api/"
  cp -a "$LIB"/ops/*.py "$WWW/ops/"
  cp -a "$LIB/chat/." "$WWW/chat/"
  cp -a "$LIB/conversation-embed.html" "$WWW/"
  chmod -R a+rX "$WWW"
fi

(umask 077
 printf 'SetEnv ORIGIN_HMAC_SECRET "%s"\nSetEnv CF_CONTAINER_API_TOKEN "%s"\n' "$SECRET" "$TOKEN" > "$APACHE/lib-secrets.conf")
chmod 0600 "$APACHE/lib-secrets.conf"
sed "s#/etc/apache2/#$APACHE/#; s#/var/www/html/lib/#$WWW/#" "$HERE/apache-lib-tunnels.conf" > "$APACHE/lib-tunnels.conf"
# The Include must precede `ProxyPass /`, or server.js answers /lib/api/tunnels, and the demo
# image's `ScriptAliasMatch` to its own tunnels.cgi (the original tunnels.rb), or since 2026-11-14 the
# Include of lib-askgk-api.conf that holds it (askgk.cgi): mod_alias takes the first matching alias.
if ! grep -q "Include $APACHE/lib-tunnels.conf" "$SITE"; then
  sed -i "0,/^\( *\)\(ScriptAliasMatch \"^\/lib\/api\/tunnels\|Include [^ ]*lib-askgk-api\.conf\|ProxyPass \/ \)/s##\1Include $APACHE/lib-tunnels.conf\n\n&#" "$SITE"
  grep -q "Include $APACHE/lib-tunnels.conf" "$SITE" || { echo "No 'ProxyPass /' in $SITE" >&2; exit 1; }
fi
echo "apache: /lib/api/tunnels -> $WWW/claude/api/tunnels.claude.rb"
sed "s#/etc/apache2/#$APACHE/#" "$HERE/apache-lib-chat.conf" > "$APACHE/lib-chat.conf"
# Startup option (main Worker var, passed to the container): only "1" turns on route-based access
# control, letting chat requests with a known route id through the admin-only lib.
if [ "${LIB_ROUTE_ACCESS_CONTROL:-}" = 1 ]; then
  cp "$HERE/apache-lib-chat-route-access.conf" "$APACHE/lib-chat-route-access.conf"
  echo "apache: route access control: on (chat routes need a known route id)"
else
  rm -f "$APACHE/lib-chat-route-access.conf"
  echo "apache: route access control: off (LIB_ROUTE_ACCESS_CONTROL is not 1)"
fi
# The chat rules must precede the vhost's catch-all WebSocket rewrite to server.js. On the demo image,
# where lib is admin-only (2026-11-11), the Include also follows the deny, so the route access grant
# (when the startup option installs it) wins for the chat routes alone.
if ! grep -q "Include $APACHE/lib-chat.conf" "$SITE"; then
  sed -i "0,/^\( *\)RewriteEngine On\$/s##&\n\1Include $APACHE/lib-chat.conf#" "$SITE"
  grep -q "Include $APACHE/lib-chat.conf" "$SITE" || { echo "No 'RewriteEngine On' in $SITE" >&2; exit 1; }
fi
echo "apache: /lib/conversation-embed.html, /lib/chat/, /lib/t/, /lib/api/chat/* -> 127.0.0.1:8092 (ws: 8091)"
# The demo image's internal vhost (127.0.0.1:8445), where tree-view's worker tab arrives through the main Worker's
# relay and server.js. Until the image carries the conversation stream relay itself (main repo PR #2660), add it.
LIB_SITE=$APACHE/sites-available/010-lib.conf
if [ ! -f "$LIB_SITE" ]; then
  echo "apache: no internal lib vhost ($LIB_SITE), nothing to relay"
elif grep -q '^[[:space:]]*ProxyPass /lib/api/chat/ ' "$LIB_SITE"; then
  echo "apache: the internal lib vhost already relays the conversation stream"
else
  cp "$HERE/apache-lib-internal-chat.conf" "$APACHE/lib-internal-chat.conf"
  if ! grep -q "Include $APACHE/lib-internal-chat.conf" "$LIB_SITE"; then
    sed -i "0,/^<\/VirtualHost>/s##    Include $APACHE/lib-internal-chat.conf\n&#" "$LIB_SITE"
    grep -q "Include $APACHE/lib-internal-chat.conf" "$LIB_SITE" || { echo "No '</VirtualHost>' in $LIB_SITE" >&2; exit 1; }
  fi
  echo "apache: 127.0.0.1:8445 /lib/api/chat/*, embed page, /lib/chat/, /lib/t/ -> 127.0.0.1:8092 (ws: 8091)"
fi

[ "${LIB_RESTORE_NO_START:-}" = 1 ] && exit 0
# lib-chat.conf sets the route-id cookie with mod_headers, which the demo image does not enable.
a2enmod headers >/dev/null
apache2ctl configtest
# Not apache2ctl: here it hands over to systemctl, which prints "Running in chroot, ignoring
# command" and exits 0, so Apache stays down or keeps its old configuration.
apache() {  # start | graceful; a minimal environment, the CGI reads PassEnv from it.
  env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}" \
    sh -c '. /etc/apache2/envvars; exec /usr/sbin/apache2 -k "$1"' sh "$1"
}
if pgrep -x apache2 >/dev/null; then apache graceful; else apache start; fi
python3 - <<'PY_CHECK'
import socket, sys, time
for _ in range(40):
    try:
        socket.create_connection(('127.0.0.1', 8443), 1).close()
        print('apache: listening on 8443')
        sys.exit(0)
    except OSError:
        time.sleep(0.25)
sys.exit('apache: nothing is listening on 8443 (see /var/log/apache2/nekoroot-error.log)')
PY_CHECK
# The demo image starts the originals (lib/ops) on the same sockets, and the start scripts
# do nothing while a socket answers. A job running in the original worker is lost.
stop_original() {  # script name in $WWW/ops
  pattern="^[^ ]*python[^ ]* $WWW/ops/$1\$"
  pkill -f "$pattern" || return 0
  for _ in $(seq 40); do
    pgrep -f "$pattern" >/dev/null || { echo "stopped the original $1"; return 0; }
    sleep 0.25
  done
  echo "the original $1 did not stop" >&2
  exit 1
}
stop_original llm_worker.py
"$HERE/start-llm-worker-claude.sh"
stop_original chat_observer.py
"$HERE/start-chat-observer-claude.sh"
"$HERE/start-chat-streams-claude.sh"
# The main Worker repo's Claude Code hooks. A failure is reported but does not undo the services above.
"$HERE/restore-claude-hooks.sh" || echo "hooks: not restored (see above)" >&2
