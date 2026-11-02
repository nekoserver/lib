#!/bin/sh
# Restore the lib/claude services on a freshly started cf-container (run as root from any directory):
#   1. copy lib/api and lib/claude/api to /var/www/html/lib (www-data cannot traverse /root)
#   2. write /etc/apache2/lib-secrets.conf (0600) from ORIGIN_HMAC_SECRET and the Cloudflare token
#   3. route /lib/api/tunnels to tunnels.claude.rb instead of server.js, then reload Apache
#   4. start the LLM worker and the chat observer
#
# Token: LIB_TUNNELS_CF_TOKEN, else CF_CONTAINER_API_TOKEN of the caller. The token that
# entrypoint.sh hands Apache (/etc/profile.d/cf-env.sh) lists no tunnels, so it is not used.
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

install -d -m 0755 "$WWW/api" "$WWW/claude/api"
cp -a "$LIB/api/." "$WWW/api/"
cp -a "$LIB/claude/api/." "$WWW/claude/api/"
chmod -R a+rX "$WWW"

(umask 077
 printf 'SetEnv ORIGIN_HMAC_SECRET "%s"\nSetEnv CF_CONTAINER_API_TOKEN "%s"\n' "$SECRET" "$TOKEN" > "$APACHE/lib-secrets.conf")
chmod 0600 "$APACHE/lib-secrets.conf"
sed "s#/etc/apache2/#$APACHE/#; s#/var/www/html/lib/#$WWW/#" "$HERE/apache-lib-tunnels.conf" > "$APACHE/lib-tunnels.conf"
# The Include must precede `ProxyPass /`, or server.js answers /lib/api/tunnels.
if ! grep -q "Include $APACHE/lib-tunnels.conf" "$SITE"; then
  sed -i "0,/^\( *\)ProxyPass \/ /s##\1Include $APACHE/lib-tunnels.conf\n\n&#" "$SITE"
  grep -q "Include $APACHE/lib-tunnels.conf" "$SITE" || { echo "No 'ProxyPass /' in $SITE" >&2; exit 1; }
fi
echo "apache: /lib/api/tunnels -> $WWW/claude/api/tunnels.claude.rb"

[ "${LIB_RESTORE_NO_START:-}" = 1 ] && exit 0
apache2ctl configtest
apache2ctl graceful
"$HERE/start-llm-worker-claude.sh"
"$HERE/start-chat-observer-claude.sh"
