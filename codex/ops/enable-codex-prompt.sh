#!/bin/sh
# Enable codex_prompt="..." on a host already set up by claude/ops/restore-claude-host.sh
# (run as root from any directory, only when Codex is needed):
#   1. link the Codex binary to the path the LLM worker runs
#   2. prepare codex-web's CODEX_HOME
#   3. copy root's Codex login to codex-web, only if codex-web has none
#
# Paths can be overridden for tests: LIB_CODEX_BIN, LIB_CODEX_LINK, LIB_CODEX_HOME,
# LIB_CODEX_AUTH_SOURCE, LIB_CODEX_USER, LIB_CODEX_SOCKET.
# LIB_RESTORE_NO_START=1 skips the worker check and the login check.
set -eu
CODEX_BIN=${LIB_CODEX_BIN:-/opt/node22/bin/codex}
CODEX_LINK=${LIB_CODEX_LINK:-/opt/codex-web/bin/codex}
CODEX_DIR=${LIB_CODEX_HOME:-/var/lib/codex-web/.codex}
AUTH_SOURCE=${LIB_CODEX_AUTH_SOURCE:-/root/.codex/auth.json}
CODEX_USER=${LIB_CODEX_USER:-codex-web}
SOCK=${LIB_CODEX_SOCKET:-/run/lib-codex/worker.sock}
START=${LIB_RESTORE_NO_START:-}
[ -x "$CODEX_BIN" ] || { echo "No Codex binary at $CODEX_BIN" >&2; exit 1; }
if [ "$START" != 1 ] && [ ! -S "$SOCK" ]; then
  echo "No LLM worker at $SOCK: run claude/ops/restore-claude-host.sh first" >&2
  exit 1
fi

install -d -m 0755 "$(dirname "$CODEX_LINK")"
ln -sfn "$CODEX_BIN" "$CODEX_LINK"
install -d -m 0700 -o "$CODEX_USER" -g "$CODEX_USER" "$CODEX_DIR"
echo "codex: $CODEX_LINK -> $CODEX_BIN"
# Never replace an existing login: its tokens may be newer than the source's.
if [ -s "$CODEX_DIR/auth.json" ]; then
  echo "codex: keeping the login in $CODEX_DIR"
elif [ -s "$AUTH_SOURCE" ]; then
  install -m 0600 -o "$CODEX_USER" -g "$CODEX_USER" "$AUTH_SOURCE" "$CODEX_DIR/auth.json"
  echo "codex: copied the login from $AUTH_SOURCE"
else
  echo "WARN: no Codex login; codex_prompt fails until $CODEX_USER signs in (see codex/README.md)" >&2
fi

[ "$START" = 1 ] && exit 0
setpriv --reuid="$CODEX_USER" --regid="$CODEX_USER" --clear-groups --no-new-privs \
  env -i HOME="$(dirname "$CODEX_DIR")" CODEX_HOME="$CODEX_DIR" PATH=/usr/local/bin:/usr/bin:/bin \
  "$CODEX_LINK" login status 2>&1 | tail -1 | sed 's/^/codex: /'
