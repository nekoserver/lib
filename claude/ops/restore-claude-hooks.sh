#!/bin/sh
# Restore the main Worker repo's Claude Code hooks after a container start (run from restore-claude-host.sh):
#   1. rebuild node_modules with `npm ci` when it is missing or a broken symlink (main has
#      committed it as a symlink to itself, so the push guard's `npx vitest` cannot load)
#   2. check every hook script named in .claude/settings.json: present and `node --check` clean
# The hooks load only in a Claude Code session started inside the repo (not in /root).
# Hook scripts are not run here: check-migration-table-registry.js posts to the Worker.
#   restore-claude-hooks.sh [repo]   (default /root/cloudflare-workers-github-oauth-1)
set -eu
REPO=${1:-/root/cloudflare-workers-github-oauth-1}
if [ ! -f "$REPO/.claude/settings.json" ]; then
  echo "hooks: skip, no $REPO/.claude/settings.json"
  exit 0
fi
cd "$REPO"

if [ ! -d node_modules ] && [ -f package-lock.json ]; then
  if [ -L node_modules ]; then
    rm node_modules
    # Keep git status clean while the symlink is still committed.
    git ls-files --error-unmatch node_modules >/dev/null 2>&1 && git update-index --skip-worktree node_modules
  fi
  npm ci --no-audit --no-fund --ignore-scripts >/tmp/restore-claude-hooks-npm.log 2>&1 \
    || { echo "hooks: npm ci failed (see /tmp/restore-claude-hooks-npm.log)" >&2; exit 1; }
  echo "hooks: node_modules rebuilt with npm ci"
fi

scripts=$(python3 -c '
import json, re, sys
hooks = json.load(open(".claude/settings.json")).get("hooks", {})
print("\n".join(sorted(set(re.findall(r"scripts/[\w.-]+", json.dumps(hooks))))))')
status=0
for s in $scripts; do
  if [ -f "$s" ] && node --check "$s" 2>/dev/null; then
    echo "hooks: OK $s"
  else
    echo "hooks: NG $s"
    status=1
  fi
done
exit $status
