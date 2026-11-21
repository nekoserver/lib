#!/bin/sh
# receiver-key.sh - muse-receiver.env の TS_API_KEY を付け替える道具。
# 鍵の正はこのファイルであり、muse-monitor のシークレットはここから配られた写し
# (SPEC.muse-monitor.security.hardening REQ-SEC-059)。付け替えは receiver 側を先に
# 行い、旧値を期限まで併せて受け付ける間に Worker 側を合わせる(REQ-SEC-063)。
# receiver.py は要求ごとにこのファイルを読み直すので、再起動は不要(REQ-SEC-064)。
#
# 使い方:
#   receiver-key.sh status          指紋だけを表示する(値は出さない)
#   receiver-key.sh rotate [時間]   新しい値を生成して正にし、旧値を期限まで併用する
#                                   (重ね期間の既定は24時間)。新しい値は、Worker の
#                                   シークレットに設定するために一度だけ表示する
#   receiver-key.sh finish          旧値の行を消す(期限切れを待たずに終えるとき)
#   receiver-key.sh set             標準入力から1行読んで、その値を正にする
#                                   (旧値は残さない。通常は rotate を使うこと)
#
# 対象ファイルは MUSE_RECEIVER_ENV、無ければ ~/.config/muse-receiver.env。
set -u
ENV_FILE="${MUSE_RECEIVER_ENV:-$HOME/.config/muse-receiver.env}"

fp() { printf %s "$1" | sha256sum | cut -c1-8; }

get_val() {
    [ -f "$ENV_FILE" ] || return 0
    v=$(grep "^$1=" "$ENV_FILE" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)
    printf %s "$v" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

# $1=現在の値 $2=旧値(空なら書かない) $3=旧値の期限(空なら書かない)
# 管理対象の3行以外はそのまま残す。書き換えは同じディレクトリの一時ファイル経由で原子的に行う。
write_env() {
    dir=$(dirname "$ENV_FILE")
    mkdir -p "$dir"
    tmp=$(mktemp "$dir/.muse-receiver.env.tmp.XXXXXX") || exit 1
    if [ -f "$ENV_FILE" ]; then
        grep -v -e '^TS_API_KEY=' -e '^TS_API_KEY_PREVIOUS=' -e '^TS_API_KEY_PREVIOUS_UNTIL=' "$ENV_FILE" > "$tmp" || true
    fi
    printf 'TS_API_KEY=%s\n' "$1" >> "$tmp"
    if [ -n "$2" ]; then printf 'TS_API_KEY_PREVIOUS=%s\n' "$2" >> "$tmp"; fi
    if [ -n "$3" ]; then printf 'TS_API_KEY_PREVIOUS_UNTIL=%s\n' "$3" >> "$tmp"; fi
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

cmd_status() {
    cur=$(get_val TS_API_KEY)
    prev=$(get_val TS_API_KEY_PREVIOUS)
    until=$(get_val TS_API_KEY_PREVIOUS_UNTIL)
    echo "ファイル: $ENV_FILE"
    if [ -n "$cur" ]; then
        echo "現在の鍵: 指紋 $(fp "$cur")"
    else
        echo "現在の鍵: 未設定(gated な経路は 503 receiver_key_not_configured)"
    fi
    if [ -n "$prev" ]; then
        echo "旧値: 指紋 $(fp "$prev")、期限 ${until:-なし(受け付けない)}"
        if [ -n "$until" ]; then
            date -d "@$until" '+       期限の日時: %Y-%m-%d %H:%M %Z' 2>/dev/null || true
        fi
    else
        echo "旧値: なし"
    fi
}

cmd_rotate() {
    hours="${1:-24}"
    case "$hours" in *[!0-9]* | '') echo "重ね期間は時間(整数)で指定する" >&2; exit 2 ;; esac
    cur=$(get_val TS_API_KEY)
    new=$(python3 -c 'import secrets; print(secrets.token_hex(32))') || exit 1
    now=$(date +%s)
    until=$((now + hours * 3600))
    if [ -n "$cur" ]; then
        write_env "$new" "$cur" "$until"
    else
        write_env "$new" "" ""
    fi
    echo "付け替えました。再起動は不要です(receiver は要求ごとに読み直します)。"
    echo "新しい TS_API_KEY(この一度だけ表示します。Worker のシークレットに設定してください):"
    echo "$new"
    echo "新しい鍵の指紋: $(fp "$new")"
    if [ -n "$cur" ]; then
        echo "旧値の指紋: $(fp "$cur")(あと ${hours} 時間は併せて受け付けます)"
    fi
    echo "次: Cloudflare の muse-monitor のシークレット TS_API_KEY に上の値を設定し、"
    echo "    ダッシュボードで section が読めることと、/status の receiverKeyFingerprint が"
    echo "    新しい鍵の指紋と一致することを確認してください。"
}

cmd_finish() {
    cur=$(get_val TS_API_KEY)
    prev=$(get_val TS_API_KEY_PREVIOUS)
    if [ -z "$prev" ]; then
        echo "旧値はありません。"
        exit 0
    fi
    write_env "$cur" "" ""
    echo "旧値(指紋 $(fp "$prev"))を消しました。"
}

cmd_set() {
    IFS= read -r new || exit 2
    new=$(printf %s "$new" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    if [ -z "$new" ]; then
        echo "空の値は設定できません" >&2
        exit 2
    fi
    write_env "$new" "" ""
    echo "設定しました。指紋: $(fp "$new")(再起動は不要です)"
}

case "${1:-}" in
    status) cmd_status ;;
    rotate) cmd_rotate "${2:-24}" ;;
    finish) cmd_finish ;;
    set) cmd_set ;;
    *)
        echo "使い方: receiver-key.sh status | rotate [時間] | finish | set" >&2
        exit 2
        ;;
esac
