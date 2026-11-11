#!/bin/sh
# ask.cgi - ダッシュボードの実行系（赤）エンドポイント。実体は ../sdk-ask-cgi.py
# Apache 側で ExecCGI と実行権限（+x）が要る。公開範囲は vhost 側の認証で制限すること。
set -u
cd "$(dirname "$0")"
exec python3 ../sdk-ask-cgi.py
