#!/bin/sh
# diag.sh - システム診断（読み取り専用）
#
# 使い方: diag.sh [-s]
#   既定: 全チェックをカテゴリ別に出力
#   -s : サマリ（件数と WARN/FAIL のみ）
# 終了コード: 0=FAIL/WARN なし, 1=WARN あり, 2=FAIL あり
# DIAG_QUICK=1 で時間のかかる走査（du、dmesg/journal 走査）を省く。
# インシデントとの対応は DIAGNOSIS.md のマトリックスを参照。
set -u

SUMMARY=0
[ "${1:-}" = "-s" ] && SUMMARY=1
QUICK=${DIAG_QUICK:-0}
ok=0; warn=0; fail=0; skip=0

report() {
  # $1=OK|WARN|FAIL|SKIP $2=カテゴリ $3=項目 $4=詳細
  case "$1" in
    OK) ok=$((ok + 1)) ;;
    WARN) warn=$((warn + 1)) ;;
    FAIL) fail=$((fail + 1)) ;;
    SKIP) skip=$((skip + 1)) ;;
  esac
  if [ "$SUMMARY" -eq 0 ]; then
    echo "[$1] $2: $3 - $4"
  elif [ "$1" = "WARN" ] || [ "$1" = "FAIL" ]; then
    echo "[$1] $2: $3 - $4"
  fi
}

has() { command -v "$1" >/dev/null 2>&1; }

echo "== diag: $(date '+%Y-%m-%d %H:%M:%S %Z') =="

# ---------- 常駐物 ----------
cat_name="常駐物"
pid=$(pgrep tailscaled 2>/dev/null | head -n 1 || true)
if [ -n "${pid:-}" ]; then
  started=$(ps -o lstart= -p "$pid" 2>/dev/null | sed 's/^ *//')
  report OK "$cat_name" "tailscaled" "PID $pid, started $started"
else
  report FAIL "$cat_name" "tailscaled" "プロセスがありません"
fi

if has curl; then
  health=$(curl -s -m 5 -w '|%{time_total}' http://127.0.0.1:8080/health 2>/dev/null || true)
  case "$health" in
    *'"status": "ok"'*|*'"status":"ok"'*)
      t=${health##*|}
      slow=$(awk -v t="$t" 'BEGIN{ print (t > 1.0) ? 1 : 0 }')
      if [ "$slow" = "1" ]; then
        report WARN "$cat_name" "API Bridge /health" "応答 ${t}s（1s 超）"
      else
        report OK "$cat_name" "API Bridge /health" "応答 ${t}s"
      fi
      ;;
    *) report FAIL "$cat_name" "API Bridge /health" "応答なし、または異常" ;;
  esac
else
  report SKIP "$cat_name" "API Bridge /health" "curl がありません"
fi

sock="$HOME/.local/share/muse/session-server/session-server.sock"
mpid=$(pgrep -f 'muse serve --listen' 2>/dev/null | head -n 1 || true)
if [ -n "${mpid:-}" ] && [ -S "$sock" ]; then
  report OK "$cat_name" "muse デーモン" "PID $mpid"
elif [ -n "${mpid:-}" ]; then
  report WARN "$cat_name" "muse デーモン" "プロセスはあるがソケットがありません"
else
  report WARN "$cat_name" "muse デーモン" "serve --listen は起動していません（spawn 方式のみ）"
fi

upsec=$(awk '{printf "%d", $1}' /proc/uptime)
if [ "$upsec" -lt 600 ]; then
  report WARN "$cat_name" "VM 稼働時間" "起動から ${upsec}s（再起動直後）"
else
  report OK "$cat_name" "VM 稼働時間" "${upsec}s"
fi

if has systemctl; then
  failed=$(timeout 10 systemctl --failed --no-legend 2>/dev/null | grep -c . || true)
  if [ "${failed:-0}" -gt 0 ]; then
    units=$(timeout 10 systemctl --failed --no-legend 2>/dev/null | awk '{print $1}' | head -n 3 | tr '\n' ' ')
    report WARN "$cat_name" "systemd 失敗ユニット" "${failed} 件: $units"
  else
    report OK "$cat_name" "systemd 失敗ユニット" "0 件"
  fi
else
  report SKIP "$cat_name" "systemd 失敗ユニット" "systemctl がありません"
fi

# ---------- CPU ----------
cat_name="CPU"
cores=$(nproc 2>/dev/null || echo 1)
load1=$(awk '{print $1}' /proc/loadavg)
loadpct=$(awk -v l="$load1" -v c="$cores" 'BEGIN{ printf "%d", (l / c) * 100 }')
if [ "$loadpct" -ge 200 ]; then
  report FAIL "$cat_name" "ロードアベレージ" "1分値 $load1（コア比 ${loadpct}%）"
elif [ "$loadpct" -ge 100 ]; then
  report WARN "$cat_name" "ロードアベレージ" "1分値 $load1（コア比 ${loadpct}%）"
else
  report OK "$cat_name" "ロードアベレージ" "1分値 $load1（コア比 ${loadpct}%）"
fi
topcpu=$(ps -eo comm=,%cpu= --sort=-%cpu 2>/dev/null | head -n 1)
report OK "$cat_name" "CPU 上位プロセス" "$topcpu"
if [ -r /proc/pressure/cpu ]; then
  psi=$(awk '/^full/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/) {sub("avg10=","",$i); print $i}}' /proc/pressure/cpu)
  report OK "$cat_name" "CPU プレッシャ (PSI full avg10)" "${psi}%"
else
  report SKIP "$cat_name" "CPU プレッシャ (PSI)" "/proc/pressure がありません"
fi

# ---------- メモリ ----------
cat_name="メモリ"
meminfo=$(cat /proc/meminfo)
mtotal=$(echo "$meminfo" | awk '/^MemTotal:/{print $2}')
mavail=$(echo "$meminfo" | awk '/^MemAvailable:/{print $2}')
if [ -n "${mtotal:-}" ] && [ "$mtotal" -gt 0 ]; then
  availpct=$((mavail * 100 / mtotal))
  if [ "$availpct" -lt 5 ]; then
    report FAIL "$cat_name" "空きメモリ" "MemAvailable ${availpct}%"
  elif [ "$availpct" -lt 10 ]; then
    report WARN "$cat_name" "空きメモリ" "MemAvailable ${availpct}%"
  else
    report OK "$cat_name" "空きメモリ" "MemAvailable ${availpct}%"
  fi
fi
stotal=$(echo "$meminfo" | awk '/^SwapTotal:/{print $2}')
sfree=$(echo "$meminfo" | awk '/^SwapFree:/{print $2}')
if [ -n "${stotal:-}" ] && [ "$stotal" -gt 0 ]; then
  swappct=$(((stotal - sfree) * 100 / stotal))
  if [ "$swappct" -ge 50 ]; then
    report WARN "$cat_name" "スワップ使用率" "${swappct}%"
  else
    report OK "$cat_name" "スワップ使用率" "${swappct}%"
  fi
else
  report SKIP "$cat_name" "スワップ使用率" "スワップがありません"
fi
if [ "$QUICK" -eq 0 ] && has dmesg; then
  oom=$(dmesg 2>/dev/null | grep -ci 'out of memory\|oom-kill' || true)
  if [ "${oom:-0}" -gt 0 ]; then
    report WARN "$cat_name" "OOM killer" "記録 ${oom} 件（dmesg）"
  else
    report OK "$cat_name" "OOM killer" "記録なし（dmesg）"
  fi
else
  report SKIP "$cat_name" "OOM killer" "QUICK または dmesg 不可"
fi
toprss=$(ps -eo comm=,rss= --sort=-rss 2>/dev/null | head -n 1 | awk '{printf "%s %d MiB", $1, $2/1024}')
report OK "$cat_name" "RSS 上位プロセス" "$toprss"

# ---------- ディスク ----------
cat_name="ディスク"
df -P 2>/dev/null | awk 'NR>1 && ($1 ~ /^\/dev\// || $6 == "/") {print $5, $6}' | while read -r use mnt; do
  pct=${use%\%}
  case "$pct" in (*[!0-9]*|'') continue ;; esac
  if [ "$pct" -ge 90 ]; then
    echo "FAIL|$mnt|${pct}%"
  elif [ "$pct" -ge 80 ]; then
    echo "WARN|$mnt|${pct}%"
  else
    echo "OK|$mnt|${pct}%"
  fi
done | while IFS='|' read -r lv mnt detail; do
  report "$lv" "$cat_name" "使用率 $mnt" "$detail"
done
imax=$(df -Pi 2>/dev/null | awk 'NR>1 {gsub("%","",$5); if ($5 > m) {m=$5; p=$6}} END {print m, p}')
ipct=${imax%% *}
if [ -n "${ipct:-}" ]; then
  if [ "$ipct" -ge 90 ]; then
    report FAIL "$cat_name" "inode 使用率（最大）" "${imax}"
  elif [ "$ipct" -ge 80 ]; then
    report WARN "$cat_name" "inode 使用率（最大）" "${imax}"
  else
    report OK "$cat_name" "inode 使用率（最大）" "${imax}"
  fi
fi
if has journalctl; then
  jsize=$(timeout 10 journalctl --disk-usage 2>/dev/null | grep -oE '[0-9.]+[KMGT]?' | head -n 1 || true)
  report OK "$cat_name" "ジャーナル使用量" "${jsize:-不明}"
else
  report SKIP "$cat_name" "ジャーナル使用量" "journalctl がありません"
fi
if [ "$QUICK" -eq 0 ]; then
  wsize=$(timeout 15 du -sh "$HOME/workspace" 2>/dev/null | awk '{print $1}')
  report OK "$cat_name" "workspace サイズ" "${wsize:-不明}"
else
  report SKIP "$cat_name" "workspace サイズ" "QUICK のため省略"
fi

# ---------- ネットワーク ----------
cat_name="ネットワーク"
if has ip; then
  route=$(ip route show default 2>/dev/null | head -n 1)
  if [ -n "$route" ]; then
    report OK "$cat_name" "デフォルト経路" "$route"
  else
    report WARN "$cat_name" "デフォルト経路" "ありません（プロキシ前提の環境では正常な場合あり）"
  fi
else
  report SKIP "$cat_name" "デフォルト経路" "ip コマンドがありません"
fi
if has getent; then
  if timeout 5 getent hosts github.com >/dev/null 2>&1; then
    report OK "$cat_name" "DNS 解決" "github.com 解決可"
  else
    report WARN "$cat_name" "DNS 解決" "github.com が解決できません（外向きはプロキシ経由のため参考値）"
  fi
else
  report SKIP "$cat_name" "DNS 解決" "getent がありません"
fi
if has ss; then
  listeners=$(ss -tuln 2>/dev/null | grep -cE '^(tcp|udp)' || true)
  report OK "$cat_name" "待ち受けポート数" "${listeners:-0}"
  tw=$(ss -ant state time-wait 2>/dev/null | grep -c . || true)
  tw=$(( ${tw:-0} > 0 ? tw - 1 : 0 ))
  if [ "$tw" -ge 1000 ]; then
    report WARN "$cat_name" "TIME_WAIT" "${tw} 件"
  else
    report OK "$cat_name" "TIME_WAIT" "${tw} 件"
  fi
else
  report SKIP "$cat_name" "待ち受けポート数" "ss がありません"
fi

# ---------- 時刻 ----------
cat_name="時刻"
if has timedatectl; then
  ntp=$(timeout 5 timedatectl show -p NTPSynchronized --value 2>/dev/null || true)
  if [ "$ntp" = "yes" ]; then
    report OK "$cat_name" "NTP 同期" "同期済み"
  elif [ -n "$ntp" ]; then
    report WARN "$cat_name" "NTP 同期" "未同期（$ntp）"
  else
    report SKIP "$cat_name" "NTP 同期" "取得できませんでした"
  fi
else
  report SKIP "$cat_name" "NTP 同期" "timedatectl がありません"
fi
report OK "$cat_name" "現在時刻" "$(date '+%Y-%m-%d %H:%M:%S %Z')"

# ---------- プロセス ----------
cat_name="プロセス"
zombies=$(ps -eo stat= 2>/dev/null | grep -c '^Z' || true)
if [ "${zombies:-0}" -gt 0 ]; then
  report WARN "$cat_name" "ゾンビプロセス" "${zombies} 件"
else
  report OK "$cat_name" "ゾンビプロセス" "0 件"
fi
procs_total=$(ps -e 2>/dev/null | grep -c . || true)
report OK "$cat_name" "プロセス総数" "${procs_total:-不明}"
if [ -r /proc/sys/fs/file-nr ]; then
  set -- $(cat /proc/sys/fs/file-nr)
  used=$1; max=$3
  if [ -n "${max:-}" ] && [ "$max" -gt 0 ]; then
    fdpct=$((used * 100 / max))
    if [ "$fdpct" -ge 80 ]; then
      report WARN "$cat_name" "ファイルハンドル" "使用 ${used}/${max}（${fdpct}%）"
    else
      report OK "$cat_name" "ファイルハンドル" "使用 ${used}/${max}（${fdpct}%）"
    fi
  fi
fi
entropy=$(cat /proc/sys/kernel/random/entropy_avail 2>/dev/null || true)
if [ -n "${entropy:-}" ]; then
  if [ "$entropy" -lt 100 ]; then
    report WARN "$cat_name" "エントロピー" "$entropy"
  else
    report OK "$cat_name" "エントロピー" "$entropy"
  fi
fi

# ---------- ログ ----------
cat_name="ログ"
if [ "$QUICK" -eq 0 ] && has journalctl; then
  errs=$(timeout 15 journalctl -p err --since '-1 hour' --no-pager -q 2>/dev/null | grep -c . || true)
  if [ "${errs:-0}" -ge 50 ]; then
    report WARN "$cat_name" "直近1時間の error ログ" "${errs} 行"
  else
    report OK "$cat_name" "直近1時間の error ログ" "${errs:-0} 行"
  fi
  panics=$(timeout 15 journalctl -k --no-pager -q 2>/dev/null | grep -ci 'panic\|segfault' || true)
  if [ "${panics:-0}" -gt 0 ]; then
    report WARN "$cat_name" "カーネルの panic/segfault" "${panics} 件"
  else
    report OK "$cat_name" "カーネルの panic/segfault" "記録なし"
  fi
else
  report SKIP "$cat_name" "ジャーナル走査" "QUICK または journalctl 不可"
fi

# ---------- ジョブ ----------
cat_name="ジョブ"
queue="$HOME/workspace/bridge-jobs/queue"
done_dir="$HOME/workspace/bridge-jobs/done"
if [ -d "$queue" ]; then
  qcount=$(ls "$queue"/*.json 2>/dev/null | grep -c . || true)
  if has python3 && [ "${qcount:-0}" -gt 0 ]; then
    oldest_age=$(python3 - "$queue" <<'PY' 2>/dev/null || echo 0
import glob, json, os, sys, time
ages = []
for p in glob.glob(os.path.join(sys.argv[1], "*.json")):
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("status") == "queued":
            ages.append(time.time() - (j.get("created") or time.time()))
    except Exception:
        pass
print(int(max(ages)) if ages else 0)
PY
)
    if [ "${oldest_age:-0}" -ge 3600 ]; then
      report WARN "$cat_name" "キューの滞留" "queued ${qcount} 件、最古は ${oldest_age}s 前"
    else
      report OK "$cat_name" "キュー" "queued ${qcount} 件"
    fi
  else
    report OK "$cat_name" "キュー" "queued ${qcount:-0} 件"
  fi
  dcount=$(ls "$done_dir"/*.json 2>/dev/null | grep -c . || true)
  report OK "$cat_name" "完了ジョブ" "done ${dcount:-0} 件"
else
  report SKIP "$cat_name" "キュー" "bridge-jobs がありません"
fi

# ---------- git ----------
cat_name="git"
unpushed_total=0
dirty_total=0
repo_count=0
for repo in "$HOME/muse-vm-hacks" $(find "$HOME/workspace" -maxdepth 3 -name .git -type d 2>/dev/null | sed 's|/.git$||'); do
  [ -d "$repo/.git" ] || continue
  repo_count=$((repo_count + 1))
  ahead=$(git -C "$repo" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
  unpushed_total=$((unpushed_total + ${ahead:-0}))
  d=$(git -C "$repo" status --porcelain 2>/dev/null | grep -c . || true)
  dirty_total=$((dirty_total + ${d:-0}))
done
if [ "$unpushed_total" -gt 0 ]; then
  report WARN "$cat_name" "未 push コミット" "合計 ${unpushed_total} 件（${repo_count} リポジトリ中）"
else
  report OK "$cat_name" "未 push コミット" "なし（${repo_count} リポジトリ）"
fi
if [ "$dirty_total" -gt 0 ]; then
  report WARN "$cat_name" "未コミット変更" "合計 ${dirty_total} 件"
else
  report OK "$cat_name" "未コミット変更" "なし"
fi

# ---------- 権限 ----------
cat_name="権限"
token="$HOME/bridge/token"
if [ -f "$token" ]; then
  mode=$(stat -c '%a' "$token" 2>/dev/null || echo "?")
  if [ "$mode" = "600" ]; then
    report OK "$cat_name" "ブリッジトークンの権限" "600"
  else
    report FAIL "$cat_name" "ブリッジトークンの権限" "$mode（600 であるべき）"
  fi
else
  report SKIP "$cat_name" "ブリッジトークンの権限" "トークンファイルがありません"
fi
state_dir="$HOME/.local/state/tailscale"
if [ -d "$state_dir" ]; then
  smode=$(stat -c '%a' "$state_dir" 2>/dev/null || echo "?")
  report OK "$cat_name" "tailscale 状態ディレクトリ" "権限 $smode"
else
  report SKIP "$cat_name" "tailscale 状態ディレクトリ" "ありません"
fi

echo "== summary: OK $ok / WARN $warn / FAIL $fail / SKIP $skip =="
if [ "$fail" -gt 0 ]; then exit 2; fi
if [ "$warn" -gt 0 ]; then exit 1; fi
exit 0
