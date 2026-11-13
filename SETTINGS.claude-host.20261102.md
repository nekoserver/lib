# cf-containerでのlib/claude（tunnels API・worker・observer）の設定手順

作成日: 2026-11-02
**対象**: Claude Codeが動くcf-container（`mygw.nekomaneki.work`、トンネル`nekoroot`） — コンテナの再起動後に、`/neko askgk`への応答と会話observerを戻す手順と、2026-11-02に行った復旧の記録。

関連: [`claude/SPEC.claude.20261102.md`](claude/SPEC.claude.20261102.md)（仕様）、[`claude/test/manual/MANUAL_CHECKS.md`](claude/test/manual/MANUAL_CHECKS.md)（手動確認）、[`claude/DESIGN.claude-engines.20261102.md`](claude/DESIGN.claude-engines.20261102.md)（CodexとClaudeの分け方）、PR [#103](https://github.com/nekoserver/lib/pull/103)。

## 構成

```
Slack /neko askgk
  → Cloudflare Worker → rust-worker-sqlx-d1
  → https://mygw.nekomaneki.work/lib/api/tunnels （HMAC署名付きPOST）
  → cloudflared（/etc/cloudflared/ingress.yml）→ Apache :8443
      /lib/api/tunnels → CGI /var/www/html/lib/claude/api/tunnels.claude.rb
      それ以外        → server.js :8080
  → LLM worker（/run/lib-codex/worker.sock）→ bwrap sandbox → claude -p（codex-webの認証）
```

会話observerは`/run/lib-chat-observer/observer.sock`で、Claude Codeのセッション記録（`/root/.claude/projects`）を配信する。

```
本体Worker /aichat のパネル（iframe）
  → https://mygw.nekomaneki.work/lib/conversation-embed.html ・ /lib/chat/ ・ /lib/t/
  → https://mygw.nekomaneki.work/lib/api/chat/{session,sse,ndjson,jsonseq} → chat_http_stream.py :8092
  → wss://mygw.nekomaneki.work/lib/api/chat/ws                             → chat_websocket.py   :8091
  → observer（/run/lib-chat-observer/observer.sock）
```

## 再起動後の手順

コンテナを再起動すると、`/var/www/html/lib`、Apacheの追加設定、worker、observer、AIチャットのストリームのサーバーはすべて消える。rootで次を1回実行する（何度実行してもよい）。

```sh
~/lib/claude/ops/restore-claude-host.sh
```

行うこと:

1. `lib/api`・`lib/claude/api`・`lib/ops`（`*.py`）・`lib/chat`・`conversation-embed.html`を`/var/www/html/lib`へ複製する。`/root`は0700で、`www-data`からは`/root/lib`を読めないため。
2. `/etc/apache2/lib-secrets.conf`（root、0600）に`ORIGIN_HMAC_SECRET`とCloudflareのトークンを書く。値は実行時の環境変数から読み、リポジトリには入れない。
3. `claude/ops/apache-lib-tunnels.conf`を`/etc/apache2/lib-tunnels.conf`に置き、`/etc/apache2/sites-available/000-demo.conf`の`ProxyPass /`より前に`Include`を1行入れる。`/lib/api/tunnels`だけをCGIへ通し、CGIのタイムアウトは330秒。
4. `claude/ops/apache-lib-chat.conf`を`/etc/apache2/lib-chat.conf`に置き、`RewriteEngine On`の直後に`Include`を1行入れる。AIチャットの埋め込みページ・資産・ストリームを8092へ、WebSocketを8091へ送る。既存の「WebSocketはすべて8080へ」の規則より前に置く必要がある。
5. `apache2ctl configtest`の後に、`apache2`を直接実行して起動または再読込し、8443の応答を確かめる。`apache2ctl`はこのコンテナでは`systemctl`に渡され、何もしないまま0で終わる。
6. `start-llm-worker-claude.sh`でworker、`start-chat-observer-claude.sh`でobserver、`start-chat-streams-claude.sh`でストリームのサーバー（`www-data`、ログ`/tmp/chat-http-stream-claude.log`・`/tmp/chat-websocket-claude.log`）を起動する。起動済みなら何もしない。
7. `restore-claude-hooks.sh`で、本体リポジトリ（`/root/cloudflare-workers-github-oauth-1`）のClaude Codeのhookを使える状態に戻す。`node_modules`が無いか、壊れたsymlink（mainに自分自身を指すsymlinkがコミットされている）なら`npm ci`で作り直し、`.claude/settings.json`が呼ぶhookスクリプトがすべて存在し`node --check`を通るかを`hooks: OK/NG`で表示する。hookスクリプト自体は実行しない（`check-migration-table-registry.js`はWorkerへ記録を送るため）。失敗しても上のサービスは止めない。
   - hookは、Claude Codeを本体リポジトリの中で起動したときだけ読み込まれる。`/root`で起動すると、日本語の強制・全体テストの禁止・push前の検査が効かない（2026-11-13に確認）。本体の作業は`cd ~/cloudflare-workers-github-oauth-1 && claude`で始める。

### 本体のデモイメージ（2026-11-12以降）での違い

デモイメージが元の`tunnels.rb`（`/usr/local/libexec/lib-api/tunnels.cgi`）、元の`llm_worker.py`・`chat_observer.py`、ストリームのサーバー（`/opt/lib-chat`のvenv、`/etc/lib-chat.env`）を起動するようになった。そのままでは`claude_prompt`は`claude_not_authenticated`、`muse_prompt`は`unsupported_engine`、先頭なしはHTTP 500、トンネル一覧は空（`no_api_token`）になる（2026-11-13確認）。`restore-claude-host.sh`はこのイメージで次のように動く。

- `Include lib-tunnels.conf`をイメージの`ScriptAliasMatch "^/lib/api/tunnels…"`より前に入れる。mod_aliasは最初に一致した別名を使うため。
- vhostが`/lib`を管理者専用にしている（利用者の判断、2026-11-11）ときは、AIチャットの経路（`lib-chat.conf`）を入れない。埋め込みページ・`/lib/api/chat/*`は公開側で403のまま。ストリームのサーバーはイメージが起動したものをそのまま使う。
- 元のworker・observerを止めてから、Claude版を起動する（同じソケットのため）。元のworkerで実行中のジョブは失われる。
- 署名ヘッダーの無いPOSTは、CGIに届く前にApacheが403を返す（以前は401）。
- `/lib`の管理者専用で公開側から止まっている機能（tree-viewのワーカータブ、AIチャットのパネル、Dockerのダッシュボードなど）は[`NOTICE.lib.20261113.lib-admin-only-impact.md`](NOTICE.lib.20261113.lib-admin-only-impact.md)にまとめた。

Claudeの認証`/var/lib/codex-web/.claude/.credentials.json`がイメージに無いときは、rootのログインを複製する（2026-11-13、利用者の判断。Codexと同じく、トークンの更新で片方が切れることがある）。

```sh
install -o codex-web -g codex-web -m 0600 /root/.claude/.credentials.json /var/lib/codex-web/.claude/.credentials.json
```

### 前提

- 環境変数`ORIGIN_HMAC_SECRET`と、トンネルを読めるCloudflareのトークン（`LIB_TUNNELS_CF_TOKEN`、無ければ`CF_CONTAINER_API_TOKEN`）。Claude Codeのシェルには両方ある。
- `codex-web`ユーザーとClaudeの認証`/var/lib/codex-web/.claude/.credentials.json`。
- Claudeのネイティブバイナリ`/opt/node22/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-x64/claude`。`/opt/node22/bin/claude`はネイティブバイナリの無いスタブで動かない。
- 2026-11-02の再起動では、認証とネイティブバイナリは起動後に用意されていた（04:22・04:26）。何が置いたかは未確認。

### トークンの注意

コンテナ起動時のトークン（`/etc/profile.d/cf-env.sh`、Apacheの環境にも入る）では`cf tunnels list --json`が`[]`を返す。Claude Codeのシェルのトークンでは一覧が取れる。そのため、復元スクリプトは実行者の環境のトークンを`lib-secrets.conf`に書く。起動時のトークン（`/cf-containers`のトークン設定）にトンネルの読取権限があるかは見直しが必要。

### observerの監視対象

既定は`workspace:/root`で、`/root`で最新のClaude Codeセッションを追う。固定する場合は次のどちらか。

- `LIB_CHAT_CLAUDE_SESSION=<セッションID>`を付けて`start-chat-observer-claude.sh`を実行する（起動中なら先に止める）。
- `/var/lib/lib-chat-observer/claude-source.json`に`{"sessionId":"…"}`か`{"followWorkspace":"/絶対パス"}`を書く。root所有、0600。

## 確認

`~/lib`で実行する。

```sh
# 単体テスト
python3 -m unittest discover -s claude/test -p '*_test.py'
ruby claude/test/tunnels_claude_rb_test.rb

# トンネル一覧（127.0.0.1からのGETはIP許可で通る）
curl -sk 'https://127.0.0.1:8443/lib/api/tunnels?status=healthy'

# askgkと同じ署名付きリクエスト（CGIを直接実行）
ruby claude/test/manual/askgk_request.rb

# 署名なしPOSTは401
curl -sk -o /dev/null -w '%{http_code}\n' -X POST https://127.0.0.1:8443/lib/api/tunnels \
  -H 'Content-Type: application/json' -d '{"message":"x"}'
```

期待する結果:

- トンネル一覧に`cfc-tunnel`・`nekoroot`がある（`"auth": "api_token"`）。
- askgkは`"ask_status": "done"`と`reply`、`llm_model: claude-opus-5-5`。数秒〜十数秒。
- 署名なしは`401`。

observerは、ソケットに`{"op":"watch"}`を送ると`type: conversation`のスナップショットが返る。

```sh
python3 -c 'import socket; s=socket.socket(socket.AF_UNIX); s.connect("/run/lib-chat-observer/observer.sock"); s.sendall(b"{\"op\":\"watch\"}\n"); print(s.makefile().readline()[:300])'
```

ログ: worker`/tmp/llm-worker-claude.log`、observer`/tmp/chat-observer-claude.log`、Apache`/var/log/apache2/nekoroot-access.log`・`nekoroot-error.log`、ジョブ記録`/var/lib/lib-llm/jobs`。


## muse_prompt

`/neko askgk muse_prompt="…"`は、workerがtailnet上の`muse-vm:8080`（OpenAI互換API）へプロンプトを送る。Codex・Claudeと違いCLIは動かさず、サンドボックスの外でHTTPを送るだけ。

- **キー**: workerを起動する環境の`MUSE_API_KEY`から読む。ファイルには書かない。起動時に環境から取り除くため、Codex・Claudeの実行からは見えない。未設定なら`muse_not_authenticated`になる。
- **接続**: このホストの`tailscaled`はuserspaceモードなので、`tailscale nc`を経由する。`tailscaled`は再起動しない（`--state=mem:`のためノードの状態が消える）。
- **反映**: workerは起動時の環境とコードを使い続ける。実行中のジョブが無いときに`llm_worker_claude.py`を止めてから、`MUSE_API_KEY`のある環境で`restore-claude-host.sh`を実行する。
- **任意の設定**: `LIB_MUSE_HOST`（既定`muse-vm`）、`LIB_MUSE_PORT`（既定`8080`）、`LIB_MUSE_MODEL`（既定`muse`）。

確認は`ruby claude/test/manual/askgk_request.rb claude/api/tunnels.claude.rb 'muse_prompt="最新ニュースを出典付きで表示してください"'`。`"via": "muse"`、`"ask_status": "done"`、`reply`が返る。

## 問い合わせの振り分け

| `message` | 送り先 | このホストでの結果 |
|---|---|---|
| 先頭なし（例: `/neko askgk トンネルの状態は？`） | Claude | 応答する。取得済みのトンネル一覧をプロンプトに添える |
| `claude_prompt="…"` | Claude | 応答する |
| `codex_prompt="…"` | Codex | 既定では`codex_execution_failed`。必要なら[`codex/README.md`](codex/README.md)の手順で有効にする |
| `muse_prompt="…"` | Muse（`muse-vm`） | 応答する。workerの起動時に`MUSE_API_KEY`が必要 |
| `nemotron_prompt="…"` | なし | `unsupported_engine`。振り分けだけあり、実行先は無い |

AIチャットのストリーム（WebSocket・SSE・NDJSON・JSON Text Sequence）では、`◯_prompt=`の文字列ではなく`{"type":"submit","engine":"◯","prompt":"△"}`でエンジンを選ぶ。`engine`は`codex`・`claude`・`muse`。

Claudeへ添えるのは`sanitize_tunnel`後の名前・ID・状態・接続数と取得時刻だけ。sandboxにはCloudflareの認証情報を渡さない。

## 症状と原因

| 症状 | 原因 | 対処 |
|---|---|---|
| `tunnelsの応答にreplyが含まれていません` | Apacheが`/lib/api/tunnels`を`server.js`へ送り、デモの固定JSON（`"message":"cloudflare-workers-github-oauth-1 demo container"`）を返している | `restore-claude-host.sh`を実行 |
| トンネル一覧が空、`"auth":"error"`・`"error":"[]\n"` | CGIに起動時のトークンが渡っている | 一覧が取れるトークンのある環境で`restore-claude-host.sh`を再実行 |
| AIチャットのパネルの表示がおかしい（埋め込みにJSONが出る、接続できない） | Apacheが`/lib/conversation-embed.html`・`/lib/api/chat/*`を`server.js`へ送り、デモの固定JSONを返している。またはストリームのサーバーが起動していない | `restore-claude-host.sh`を実行。`ss -ltn`で8091・8092を確認 |
| `codex_worker_unavailable` | workerが起動していない | `claude/ops/start-llm-worker-claude.sh` |
| `claude_not_authenticated` | `codex-web`のClaude認証が無い | `/var/lib/codex-web/.claude/.credentials.json`を用意 |
| 先頭なしの質問でCGIが落ちる（`/var/lib/lib-api/ask`の`Errno::ENOENT`） | 元の`tunnels.rb`の動作（参謀`ask_sanbo.rb`へ送る） | `tunnels.claude.rb`を使う（PR #103で対応） |
| 「トンネルは動いていない」と誤答 | sandboxからは`cf`もcloudflaredも見えない | PR #103でトンネル一覧をプロンプトに添える |
| シェルの`find`・`grep`が`claude native binary not installed`で失敗 | Claude Codeのシェル関数が、ネイティブバイナリの無い`claude.exe`を呼ぶ | `command find`・`command grep`を使う |
| workerのログに`BrokenPipeError` | 起動スクリプトの生存確認（接続してすぐ切る） | 害はない |

## 2026-11-02の復旧の記録

1. 再起動後、worker・observerは止まり、`/run`・`/var/lib`の状態も消えていた。単体テストは通った。
2. workerを起動。CGIを直接実行してトンネル一覧とaskgkの応答を確認した。
3. observerを本来のソケットで起動（`workspace:/root`）し、`watch`でこの会話が届くことを確認した。
4. Slackからの`/neko askgk`がreplyなしで失敗。Apacheのアクセスログで要求の到着を確認し、`server.js`の汎用応答が原因と特定した。
5. `/var/www/html/lib`への複製、`lib-secrets.conf`、vhostへのCGIの設定でreplyが返るようにした。一覧が空だったのは起動時のトークンが原因だったため、シェルのトークンに替えた。
6. 手順を`restore-claude-host.sh`にまとめ、vhostを元に戻してからスクリプトで再構成して確認した。
7. 先頭なしの質問が参謀へ行って落ちること、Claudeがトンネル停止と誤答することを直した（テストを先に追加）。
8. ブランチ`fix/claude-askgk-restore-20261102`にコミットし、PR #103を作成した。

## 未対応

- Slackからの`/neko askgk`での確認（PR #103の修正後は未実施）。Apache経由の署名付きPOSTでは確認済み。
- 再起動時の自動実行。cf-containerの`entrypoint.sh`から`restore-claude-host.sh`を呼ぶ必要がある。ただし起動時の環境にはトンネルを読めるトークンが無いため、トークンの扱いを先に決める。
- `/neko askgk`のWorker側の待ち時間（D1、既定120秒）。300秒待たせるには本番の`/settings`の変更が必要。
- `codex_prompt=`の扱い（DESIGNメモの方針2・3）。
