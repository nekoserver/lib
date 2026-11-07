# NOTICE: lib/claudeの設定を実行したときの記録

日付: 2026-11-07

**対象**: cf-containerでの`claude/ops/restore-claude-host.sh`と`codex/ops/enable-codex-prompt.sh`の実行 — 手順書どおりに動いたことと、確認で気づいたことの記録。手順は[`SETTINGS.claude-host.20261102.md`](SETTINGS.claude-host.20261102.md)。

## 結果

| 確認 | 結果 |
|---|---|
| `claude_prompt`、`muse_prompt`、`codex_prompt`、先頭なし | 応答あり |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| WebSocket、SSE | claude、muse、codexで応答あり（Apache経由） |
| NDJSON、JSON Text Sequence | museで応答あり（Apache経由） |
| observerの配信と送信 | 配信はWebSocketとSSEで受信。送信は手順書の確認用セッションで成功 |
| 署名なしのPOST、送信 | 401 |
| 公開URL | セッション発行、埋め込みページ、tunnels APIの`muse_prompt`のみ確認 |

未確認: Slackからの`/neko askgk`、公開URL経由のWebSocketとSSE。

## 確認で気づいたこと

- **`cfc-tunnel`が一覧に出ない。** `status=healthy`では`nekoroot`だけだった。手順書は両方あると書いている。healthyでないだけかは未確認
- **埋め込みページは未認証だと401が正しい。** `/lib/conversation-embed.html`と`/lib/chat/`はセッションのCookieがあれば返る。401を不具合と間違えない
- **`chat/`の資産はハッシュ付きの名前もある。** `app.js`は404で正しい。実物は`app.mjs`など
- **WebSocketの試験で`Host`を二重に送ると400になる。** `websockets`の`additional_headers`に`Host`を足した試験側の誤りで、サーバーの問題ではない
- **`enable-codex-prompt.sh`は`/root/.codex/auth.json`を`codex-web`へコピーする。** rootと同じChatGPTのログインを共有するので、更新で片方が切れることがある

## シェルの注意

- Claude Codeのシェルでは`find`、`grep`が関数に置き換わる。実体が無いと`claude native binary not installed`で失敗するので、`command find`、`command grep`を使う
- `pkill -f`の検索文字列は、同じ行で実行中のシェル自身にも一致する。`pkill`と待機を同じコマンドに書くと、待機も止まる
- `tailscale nc`は標準入力を閉じると応答を受け取る前に終わる。`( printf ...; sleep 3 ) | tailscale nc ...`のように開けておく
- `tail -n 5 a b`を使う。`tail -5 a b`は失敗する
- スクラッチパッドのディレクトリは最初から存在するとは限らない。使う前に`mkdir -p`する

## 問い合わせの注意

- `askgk_request.rb`は`timeout`で切っても、workerのジョブは続く。結果は`/var/lib/lib-llm/jobs`で読める
- ジョブの上限は300秒。`llm_timeout`になる前に質問を分ける
- Museの応答は30秒から5分まで幅がある。Slackの待ち時間（既定120秒）を超えることがある
