#!/bin/bash
# このコンテナのログイン時にネットワークを検査する。
step() {
    local label=$1
    shift
    if "$@"; then
        printf '[成功] %s\n' "$label"
    else
        printf '[失敗] %s\n' "$label"
        failed=$((failed + 1))
    fi
}

restore_apache() {
    local active=/etc/apache2/sites-available/010-lib.conf
    local expected=$worker/containers/demo/apache-lib.conf
    local backup=$active.pre-network-20261121
    apache2ctl configtest || return 1
    if cmp -s "$active" "$expected"; then
        return 0
    fi
    if ! cmp -s "$active" "$backup"; then
        printf '内部 Apache に別の設定変更があります。稼働検査を続けます。\n'
        return 1
    fi
    install -m 0644 "$expected" "$active" || return 1
    if apache2ctl configtest && apache2ctl -k graceful; then
        return 0
    fi
    install -m 0644 "$backup" "$active"
    return 1
}

capture_firewall() {
    local output=/root/firewall-login
    local source snapshot
    install -d -m 0700 "$output" || return 1
    for source in firewall.log firewall-collector.log nftables.log; do
        install -m 0600 "/tmp/$source" "$output/$source" || return 1
    done
    snapshot=$(mktemp "$output/nft-filter.XXXXXX") || return 1
    if nft -j list table inet filter >"$snapshot"; then
        mv -f "$snapshot" "$output/nft-filter.json"
    else
        rm -f "$snapshot"
        return 1
    fi
}

run_checks() {
    local prompt=$1 panel=$2 failed=0 host
    printf '\n=== ログイン時ネットワーク検査 %s ===\n' "$(date -u +%FT%TZ)"
    step '内部 Apache 設定' restore_apache
    step 'Codex 専用認証' "$here/enable-codex-prompt.sh"
    step 'root 専用 app-server' /usr/bin/python3 /root/cf-container/ops/network/start-lib-chat-app-server 9>&-
    step 'ENV 優先とトンネルキャッシュ' /usr/bin/python3 -B "$tests/network_settings_test.py"
    step 'CGI・SSI・非公開パス・ソケット' /usr/bin/python3 -B "$tests/network_runtime_test.py"
    step '署名付きトンネル一覧と4方式の配信' /usr/bin/python3 -B "$here/network-boot-live.py"
    if (( prompt )); then
        step '引用符付き Codex プロンプトの実応答' /usr/bin/python3 -B "$here/network-boot-live.py" --prompt
    fi
    if (( panel )); then
        step '公開ストリームパネルの投稿と返信' /usr/bin/python3 -B "$here/network-boot-live.py" --browser
    fi
    printf '%s\n' '=== 公開経路 ==='
    for host in mygw.nekomaneki.work stream.test.cfc r9.nekomaneki.work; do
        step "$host" curl --fail --silent --show-error --max-time 8 --output /dev/null \
            --write-out 'HTTP=%{http_code}\n' "https://$host/"
    done
    printf '%s\n' '=== 既存 APT 索引の更新候補 ==='
    step '更新候補の取得' apt list --upgradable
    step 'ファイアウォール採取' capture_firewall
    printf '=== 完了 %s 失敗項目=%d ===\n' "$(date -u +%FT%TZ)" "$failed"
    (( failed == 0 ))
}

main() {
    set -u
    umask 077
    PATH=/opt/node22/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
    export PATH
    local here
    here=$(cd -- "$(dirname -- "$0")" && pwd) || return 1
    local tests=/root/cf-container/ops/test
    local worker=/root/cloudflare-workers-github-oauth-1
    local prompt=0 panel=0 argument
    for argument in "$@"; do
        case "$argument" in
            --prompt) prompt=1 ;;
            --panel) panel=1 ;;
            -h|--help)
                printf '使用方法: %s [--prompt] [--panel]\nログ: /root/boot.log\n' "$0"
                return 0 ;;
            *) printf '不明なオプション: %s\n' "$argument" >&2; return 2 ;;
        esac
    done
    if (( EUID != 0 )); then
        printf 'root で実行してください。\n' >&2
        return 1
    fi
    mkdir -p -m 0700 /run/lib-network-login || return 1
    exec 9>/run/lib-network-login/lock || return 1
    if ! flock -n 9; then
        printf 'ネットワーク起動検査はすでに実行中です。\n' >&2
        return 1
    fi
    touch /root/boot.log || return 1
    chmod 0600 /root/boot.log || return 1
    exec >>/root/boot.log 2>&1
    run_checks "$prompt" "$panel"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
