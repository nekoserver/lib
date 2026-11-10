#!/bin/sh
# graphs.sh - 主要メトリクスの棒グラフを HTML 断片で出力する（読み取り専用）
#
# SSI の #exec から直接呼ばれる前提で、完成した HTML を出す
# （他のスクリプトと違い、呼び出し側でのエスケープはしない。
#   ラベルに &<>" が混ざらないよう、ここで除去している）
set -u

bar() {
  # $1=label $2=value $3=max $4=unit
  pct=$(awk -v v="$2" -v m="$3" 'BEGIN{ if (m<=0) p=0; else { p=v/m*100; if (p>100) p=100 } printf "%.0f", p }')
  printf '<div class="grow"><span class="glabel">%s</span><span class="gbar" style="width:%s%%"></span><span class="gval">%s %s</span></div>\n' "$1" "$pct" "$2" "$4"
}

echo '<h3>メモリ使用量（プロセス上位）</h3>'
max=$(ps -eo rss= --sort=-rss 2>/dev/null | head -n 1)
ps -eo comm=,rss= --sort=-rss 2>/dev/null | head -n 8 | while read -r comm rss; do
  label=$(printf '%s' "$comm" | tr -d '&<>"')
  bar "$label" $((rss / 1024)) $((max / 1024)) "MiB"
done

echo '<h3>メモリ / スワップ使用量</h3>'
free -m 2>/dev/null | awk '/^Mem:/{print "Mem", $3, $2} /^Swap:/{print "Swap", $3, $2}' | while read -r name used total; do
  bar "$name" "$used" "$total" "MiB"
done

echo '<h3>ディスク使用量</h3>'
df -P / "$HOME" 2>/dev/null | awk 'NR>1 && !seen[$6]++ {print $6, $3, $2}' | while read -r mnt used total; do
  bar "$mnt" $((used / 1024)) $((total / 1024)) "MiB"
done
