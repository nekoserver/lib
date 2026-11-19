#!/bin/sh
# Restore the main Worker repo's Claude Code hooks after a container start (run from restore-claude-host.sh):
#   1. rebuild node_modules with `npm ci` when it is missing or a broken symlink (main has
#      committed it as a symlink to itself, so the push guard's `npx vitest` cannot load)
#   2. check every hook script named in .claude/settings.json: present and `node --check` clean
#   3. copy the hooks that work in any directory into ~/.claude/settings.json with absolute paths
# The repo's hooks load only in a Claude Code session started inside the repo. A session started in /root
# had none, and a full `npx vitest run` went through on 2026-11-19 (AGENT.md forbids it in this container).
# Step 3 covers that session. Left out: the push guard (runs git in its working directory) and the
# migration check (posts to the Worker). A session started in the repo runs a guard from both files; the
# guards only block or add an instruction, so running twice changes nothing. ~/.claude does not survive
# a container restart, so this runs after every start; earlier entries are replaced, other settings kept.
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

# Step 3. Only scripts that passed the check above.
USER_GUARDS="claude-full-test-guard.js claude-japanese-guard.js claude-self-check-guard.js"
ok=""
for g in $USER_GUARDS; do
  if echo "$scripts" | grep -qx "scripts/$g" && [ -f "scripts/$g" ] && node --check "scripts/$g" 2>/dev/null; then
    ok="$ok $g"
  fi
done
mkdir -p "$HOME/.claude"
python3 - "$(pwd -P)" "$HOME/.claude/settings.json" $ok <<'PY'
import json, os, re, sys
repo, path, guards = sys.argv[1], sys.argv[2], sys.argv[3:]
names = 'claude-full-test-guard.js claude-japanese-guard.js claude-self-check-guard.js'.split()
try:
    settings = json.load(open(path))
except (OSError, ValueError):
    settings = {}
hooks = settings.get('hooks', {})
mine = re.compile(r'^node "/[^"]*/scripts/(%s)"$' % '|'.join(map(re.escape, names)))
for event in list(hooks):  # drop what an earlier run installed (any repo path)
    groups = []
    for group in hooks[event]:
        kept = [h for h in group.get('hooks', []) if not mine.match(h.get('command', ''))]
        if kept:
            groups.append(dict(group, hooks=kept))
    if groups:
        hooks[event] = groups
    else:
        del hooks[event]
project = json.load(open('.claude/settings.json')).get('hooks', {})
installed = 0
for event, groups in project.items():
    for group in groups:
        picked = []
        for h in group.get('hooks', []):
            m = re.search(r'scripts/([\w.-]+)', h.get('command', ''))
            if m and m.group(1) in guards:
                picked.append(dict(h, command=f'node "{repo}/scripts/{m.group(1)}"'))
        if picked:
            hooks.setdefault(event, []).append(dict(group, hooks=picked))
            installed += len(picked)
settings['hooks'] = hooks
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
os.replace(tmp, path)
print(f'hooks: user level {path}: {installed} hooks ({" ".join(guards) or "none"})')
PY

# Scripts that exist and parse are not hooks that work: run the installed full test guard command from
# outside the repo, as Claude Code would for a session started in /, and expect it to block (exit 2).
guard=$(python3 -c '
import json, sys
for g in json.load(open(sys.argv[1])).get("hooks", {}).get("PreToolUse", []):
    for h in g.get("hooks", []):
        if h.get("command", "").endswith("/scripts/claude-full-test-guard.js\""):
            print(h["command"]); sys.exit()' "$HOME/.claude/settings.json")
probe() {  # command for the hook input -> exit code of the installed guard
  printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"/","tool_input":{"command":"%s"}}' "$1" \
    | (cd / && sh -c "$guard") >/dev/null 2>&1 && echo 0 || echo $?
}
if [ -z "$guard" ]; then
  echo "hooks: NG the full test guard is not in $HOME/.claude/settings.json"
  status=1
elif [ "$(probe 'npx vitest run')" = 2 ] && [ "$(probe 'git status')" = 0 ]; then
  echo 'hooks: works: the full test guard stops `npx vitest run` outside the repo'
else
  echo 'hooks: NG the full test guard did not stop `npx vitest run` (or stopped `git status`)'
  status=1
fi
exit $status
