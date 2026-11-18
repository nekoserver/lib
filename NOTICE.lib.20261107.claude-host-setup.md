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

## 追記: 2回目の実行とMuseの再起動（2026-11-07 17時台）

コンテナの起動後、Apache・worker・observer・ストリームのサーバーが止まっていたため、同じ2本（`restore-claude-host.sh`、`enable-codex-prompt.sh`）を再び実行した。前提（`ORIGIN_HMAC_SECRET`、Cloudflareのトークン、`MUSE_API_KEY`、`codex-web`のClaude認証、ネイティブバイナリ）は実行前から揃っていた。単体テストはclaude 33件、Ruby 6件、codex 8件が通った。

| 確認 | 結果 |
|---|---|
| tunnels APIの`claude_prompt`、`codex_prompt`、`muse_prompt`、先頭なし | `ask_status: done`（`claude-opus-5-5`、`gpt-6.1-sol`、`muse`） |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| WebSocket、SSE、NDJSON、JSON Text Sequence | claude、codex、museの全組合せで`done`（Apache経由、HMAC署名） |
| 未対応の`engine`（ストリーム） | 400 |
| observer | `watch`とWebSocketの`observe`でスナップショットを受信 |
| 署名なしのPOST（tunnels API、SSE） | 401 |
| トンネル一覧（`status=healthy`） | `nekoroot`のみ。`cfc-tunnel`は出ない（1回目と同じ） |

その後、利用者がMuse（`muse-vm`）を再起動した。こちらはworkerもApacheも再起動せずに、tunnels APIの`muse_prompt`、WebSocket、SSE、NDJSON、JSON Text Sequenceのすべてで`done`が返った。workerは要求ごとに`tailscale nc`で`muse-vm:8080`へつなぐため、Muse側の再起動ではこのホストの操作は要らない。

未確認: Slackからの`/neko askgk`、公開URL経由のWebSocketとSSE（1回目と同じ）。

### 確認の方法

- tunnels API: `ruby claude/test/manual/askgk_request.rb claude/api/tunnels.claude.rb '<engine>_prompt="hello"'`
- ストリーム: `https://127.0.0.1:8443/lib/api/chat/{sse,ndjson,jsonseq}`へ`Origin: https://mygw.nekomaneki.work`、`X-Timestamp`、`X-Signature`（`POST\n<path>\n<timestamp>\n<bodyのsha256>`のHMAC）付きで`{"type":"submit","engine":"◯","prompt":"△"}`をPOSTする。最後の`type: job`の`ask_status`を見る
- WebSocket: `wss://127.0.0.1:8443/lib/api/chat/ws`へ`Origin`付きで接続し、`challenge`の`nonce`に`WS\n/lib/api/chat/ws\n<nonce>`のHMACを`{"type":"auth","signature":…}`で返してから、同じ`submit`を送る。`Host`は足さない（二重になると400）
- ストリームは、`job`イベントの`ask_status`が`pending`・`running`の間は`job`か`heartbeat`が続き、`done`か`failed`の`job`で終わる。Museでは返答の前に`heartbeat`が十数回続いた

## 追記: 3回目の実行（2026-11-07 19時台）

コンテナの起動後、Apache・worker・observer・ストリームのサーバーが止まっていたため、同じ2本（`restore-claude-host.sh`、`enable-codex-prompt.sh`）を再び実行した。前提（`ORIGIN_HMAC_SECRET`、`CF_CONTAINER_API_TOKEN`、`MUSE_API_KEY`、`codex-web`のClaude認証、ネイティブバイナリ）は実行前から揃っていた。`codex-web`にはCodexのログインが無く、`/root/.codex/auth.json`からコピーされた（`Logged in using ChatGPT`）。単体テストはclaude 33件、Ruby 6件、codex 8件が通った。

| 確認 | 結果 |
|---|---|
| tunnels APIの`claude_prompt`、`codex_prompt`、`muse_prompt`、先頭なし | `ask_status: done`（`claude-opus-5-5`、`gpt-6.1-sol`、`muse`、先頭なしは`claude-opus-5-5`） |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| WebSocket、SSE、NDJSON、JSON Text Sequence | claude、codex、museの全12通りで`done`（Apache経由、HMAC署名） |
| 未対応の`engine`（SSE、`nemotron`） | 400 |
| observer | WebSocketの`observe`で`conversation`のスナップショットを受信 |
| 署名なしのPOST（tunnels API、SSE） | 401 |
| トンネル一覧（`status=healthy`） | `nekoroot`のみ。`cfc-tunnel`は出ない（1回目・2回目と同じ） |

未確認: Slackからの`/neko askgk`、公開URL経由のWebSocketとSSE（1回目・2回目と同じ）。

### 同時実行で気づいたこと

- **ストリームの12通りと未対応・署名なしの確認を同時に流すと、NDJSONとJSON Text Sequenceの4本が正しく終わらなかった。** codexの2本は最後の`job`が`pending`のまま、museの2本は`failed`で終わった。1本ずつ流し直すと4本とも`done`になった
- そのとき`/var/lib/lib-llm/jobs`の記録とworkerのログはすべて`done`で、museのジョブは要求した数より少なかった。失敗した要求はworkerに届く前に終わったとみられる。`/tmp/chat-http-stream-claude.log`は空で、原因は未調査
- 手動の確認でストリームを同時にたくさん流すと失敗と見分けにくい。エンジンごとに分けるか、1本ずつ流す

## 追記: 4回目の実行（2026-11-07 22時台）

コンテナの起動後、Apache・worker・observer・ストリームのサーバーが止まっていたため、同じ2本（`restore-claude-host.sh`、`enable-codex-prompt.sh`）を再び実行した。前提（`ORIGIN_HMAC_SECRET`、`CF_CONTAINER_API_TOKEN`、`MUSE_API_KEY`、`codex-web`のClaude認証、ネイティブバイナリ）は実行前から揃っていた。`codex-web`にはCodexのログインが無く、`/root/.codex/auth.json`からコピーされた（`Logged in using ChatGPT`）。単体テストはclaude 33件、Ruby 6件、codex 8件が通った。

| 確認 | 結果 |
|---|---|
| tunnels APIの`claude_prompt`、`codex_prompt`、`muse_prompt`、先頭なし | `ask_status: done`（`claude-opus-5-5`、`gpt-6.1-sol`、`muse`、先頭なしは`claude-opus-5-5`） |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| WebSocket、SSE、NDJSON、JSON Text Sequence | claude、codex、museの全12通りで`done`（Apache経由、HMAC署名、1本ずつ順に実行） |
| 未対応の`engine`（SSE、`nemotron`） | 400 |
| observer | ソケットの`watch`で`conversation`のスナップショットを受信 |
| 署名なしのPOST（tunnels API、SSE） | 401 |
| トンネル一覧（`status=healthy`） | `nekoroot`のみ。`cfc-tunnel`は出ない（1〜3回目と同じ） |

未確認: Slackからの`/neko askgk`、公開URL経由のWebSocketとSSE（1〜3回目と同じ）。

## 追記: 新しいデモイメージでの実行（2026-11-13）

デモイメージが元のtunnels.rb・worker・observerを起動するようになり、`restore-claude-host.sh`がそのままでは切り替えられなかった（イメージの`ScriptAliasMatch`が先に一致し、元のworker・observerがソケットを持ったまま）。スクリプトを直し（手順は`SETTINGS.claude-host.20261102.md`の「本体のデモイメージ」）、`codex-web`にrootのClaudeのログインを複製してから実行した。`/lib`の管理者専用（2026-11-11の判断）は変えていない。

| 確認 | 結果 |
|---|---|
| tunnels API（Apache経由、署名付き）の`claude_prompt`、`codex_prompt`、`muse_prompt`、先頭なし | `done`（`claude-opus-5-5`、`gpt-6.1-sol`、`muse`、先頭なしは`claude-opus-5-5`）。トンネル一覧は`cfc-tunnel`・`nekoroot` |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| SSE、NDJSON、JSON Text Sequence、WebSocket（127.0.0.1:8092・8091へ直接） | claude、codexの8通りで`done`。museはSSEで`done`（約97秒）。`nemotron`は400 |
| observer（WebSocketの`observe`） | この会話（Claude Codeのセッション）のスナップショットを受信 |
| 署名なしのPOST | 403（Apacheの`Require expr`） |

未確認: Slackからの`/neko askgk`、管理者のプロキシ（:8080）経由のストリーム、museのNDJSON・JSON Text Sequence・WebSocket。

## 追記: デモイメージの変更後の実行（2026-11-14）

イメージの`/lib/api/tunnels`の別名が`lib-askgk-api.conf`の`Include`に移り、`restore-claude-host.sh`の`Include`がその後ろに入ってイメージの`askgk.cgi`が先に一致した。トークンが渡らずトンネル一覧が`no_api_token`、こちらの別名に替えると`cf tunnels list --json`が`Unknown argument: json`になった。テストを先に足して、`Include`の位置と`--json`を直した（手順は`SETTINGS.claude-host.20261102.md`の「デモイメージの変更（2026-11-14確認）」）。hookは`npm ci`で`node_modules`を作り直し、5本とも`hooks: OK`。単体テストはclaude 80件、Ruby 7件が通った。

| 確認 | 結果 |
|---|---|
| tunnels API（Apache経由、署名付き）の`claude_prompt`、`codex_prompt`、`muse_prompt`、先頭なし | `done`（`claude-opus-5-5`、`gpt-6.1-sol`、`muse`、先頭なしは`claude-opus-5-5`）。一覧は`nekoroot`（`status=healthy`） |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| SSE、NDJSON、JSON Text Sequence、WebSocket（127.0.0.1:8092・8091へ直接） | claude、codex、museの全12通りで`done`。`nemotron`は400 |
| observer | ソケットの`watch`とWebSocketの`observe`で`conversation`を受信 |
| 署名なしのPOST | 403 |

未確認: Slackからの`/neko askgk`、管理者のプロキシ（:8080）経由のストリーム。

## 追記: コンテナ再起動後の実行（2026-11-18）

再起動後、Apache・worker・observer・ストリームのサーバーが止まっていたため、`restore-claude-host.sh`を実行した（利用者が`!`で実行。Claude Codeの自動許可では、`/etc/apache2`への秘密の書込みとサービスの入れ替えのため拒否された）。前提（`ORIGIN_HMAC_SECRET`、`CF_CONTAINER_API_TOKEN`、`MUSE_API_KEY`、`codex-web`のClaude認証、ネイティブバイナリ）は実行前から揃っていた。hookは`npm ci`で作り直し、5本とも`hooks: OK`。単体テストはclaude 80件、Ruby 7件、`llm_prompt` 17件、`chat_websocket` 13件が通った。

| 確認 | 結果 |
|---|---|
| tunnels API（CGIを直接、署名付き）の`claude_prompt`、先頭なし | `done`（`claude-opus-5-5`）。先頭なしはトンネル一覧（`nekoroot`・`term-root`）を根拠に答えた |
| tunnels APIの`muse_prompt` | 1回目は`llm_timeout`（300秒、Muse側の応答待ち。`muse-vm`はtailnetで`active`）。2回目は`done`（約155秒） |
| tunnels APIの`codex_prompt` | `codex_execution_failed`。`enable-codex-prompt.sh`は未実行。rootにCodexのログイン（`/root/.codex/auth.json`）が無く、実行しても複製元が無い |
| `nemotron_prompt` | `unsupported_engine`（仕様どおり） |
| SSE、NDJSON、JSON Text Sequence、WebSocket（127.0.0.1:8092・8091へ直接） | claude、museの全8通りで`done`（muse 20〜102秒）。codexはSSEで`codex_execution_failed`。`nemotron`はSSEで400、WebSocketで`invalid_request` |
| observer | SSEとWebSocketの`observe`で`conversation`を受信 |
| Apache経由（8443）、修正前 | 署名の有無にかかわらず`/lib/api/tunnels`も403。Slackの`/neko askgk`も`HTTP 403`で失敗した（下記） |
| Apache経由（8443）、修正後 | 署名付きの`claude_prompt`は`done`（約7秒）、`muse_prompt`は`done`（約28秒）。署名なしは403、不正な署名は401（CGI）、`/lib`のほかのパスは403 |

- workerは1件ずつ処理するため、同時に5件送ると、museの300秒の待ちの後ろで、claude・codexの応答も約320秒かかった。点検は1件ずつ送る。
- トンネル一覧の2本目は`cfc-tunnel`ではなく`term-root`になっていた。
- **askgkの403**: このイメージのvhostは`<LocationMatch "^/(?:debug|admin|lib)(?:/|$)">`で`/lib`をすべて拒否し、以前のイメージにあった公開側の例外（`lib-askgk-api.conf`、本体SPEC`lib-access-control`の「公開Apacheの例外」）が無くなっていた。Workerの署名付きPOSTはCGIに届く前に403になる。`claude/ops/apache-lib-tunnels.conf`に、`/lib/api/tunnels`だけを署名ヘッダーがあるときに通す`<LocationMatch>`を足した（vhostの拒否の後でIncludeされるため優先される）。テストは`claude/test/apache_lib_tunnels_test.py`（使い捨てのApacheで、修正前に403で失敗することを確かめた）。反映には`restore-claude-host.sh`の再実行が要る（Apacheの設定の変更として、Claude Codeの自動許可では拒否された）。
- CGIを直接実行する確認（`askgk_request.rb`）はApacheの拒否を通らない。Slackからの経路の確認には、Apache経由の署名付きPOSTを使う。

未確認: Slackからの`/neko askgk`（修正後）、管理者のプロキシ（:8080）経由、`codex_prompt`（Codexのログインが必要）。

### `/lib`のアクセス制限は何のためか、その前はどうだったか

**対象**: 本体のdemoコンテナの公開Apache（:8443、`mygw.nekomaneki.work`、トンネル`nekoroot`）での`/lib`の拒否と、tunnels API（`/lib/api/tunnels`）の例外 — 今回のaskgkの403の背景として、制限を入れた目的と、入れる前の状態を記録する。根拠は本体リポジトリのコミット・SPECと、libのNOTICE（下の「根拠」）。

#### 何のために制限したか（2026-11-11、利用者の判断「管理者だけ」）

- **libには、コンテナの中を見せるページがある。** `/lib`はSSI（`#exec`を含む）とCGIを実行する。`ls_-la.shtml`・`printenv.shtml`・`ip.shtml`・`ps`系などは、コンテナの中でコマンドを実行し、その出力（ファイル一覧、環境、ネットワーク）をそのまま返す。誰でも開けると、コンテナの内部が外から見える。
- **公開の入口は、何もしなければ全部を素通しにしていた。** 公開のApache（8443）は`/`以下をすべて`server.js`（8080）へ回す。本体のコミット[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62)の説明は「拒否しないとトンネル経由で公開されていた」。
- **そこで、`/lib`を見られる人を、本体ワーカーにログインした管理者に限った。** 同じコミットで、次の2つを同時に入れた。
  - 公開の8443では`/lib`を拒否する。それまで拒否していた`/debug`・`/admin`（ログや通信の調査用）と同じ扱いにした。vhostの`<LocationMatch "^/(?:debug|admin|lib)(?:/|$)">`の`Require all denied`。
  - 管理者用の入口を新しく作った。本体ワーカーの`/cf-containers/proxy/lib/...`（ログインと管理者の確認がある）から、`server.js`（8080）を経て、`127.0.0.1:8445`だけで待ち受ける内部のApache（`apache-lib.conf`、`Require local`）へ渡す。
- 公開の入口とワーカー経由の入口は、同じ`/var/www/html/lib`を見る。違うのは、途中で誰を確かめるかだけである（本体`SPEC.cloudflare-workers-github-oauth-1.20261115.lib-access-via-worker.md`）。

#### 制限する前はどうだったか（〜2026-11-10）

| 経路 | 制限の前 | 制限の後 |
|---|---|---|
| `/lib/*.shtml`などのSSI・CGI | 本体のイメージには、そもそも`/lib`のSSIの入口が無かった。8443の`/`以下は`server.js`へ回るだけで、`/lib`を守る設定も無かった | 公開側は403。管理者はワーカー経由（`/cf-containers/proxy/lib/...` → 8445）で見る |
| `/lib/api/tunnels`（Slackの`/neko askgk`） | `restore-claude-host.sh`（2026-11-02〜）が8443にCGIの別名を入れ、公開側から届いていた。Apacheは何も確かめず、CGIがHMAC署名かIP許可で確かめる。署名なしは401（CGI） | 2026-11-11のコミットには例外が無く、`/lib`の拒否にaskgkも巻き込まれた。2026-11-13に、署名ヘッダーがあるときだけ通す例外がイメージ側に入った。署名なしは403（Apache）、不正な署名は401（CGI） |
| `/lib/conversation-embed.html`・`/lib/chat/`・`/lib/t/`・`/lib/api/chat/*`（AIチャットのパネル、tree-viewのワーカータブ） | `restore-claude-host.sh`がストリームのサーバー（8091・8092）へ回していた。ログイン・HMACのセッション・`frame-ancestors`で守られていた | 公開側は403になり、パネルに「Forbidden」が出た（2026-11-13）。起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ、経路IDのある要求を通す（PR #147、`NOTICE.lib.20261113.lib-admin-only-impact.md`） |
| `/debug`・`/admin` | 2026-10-27から公開側は拒否（本体[`4fde15d1`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/4fde15d1)） | 変わらない |

#### 今回（2026-11-18）の403との関係

- 2026-11-13・14のイメージでは、tunnels APIの例外があった（vhostの`^/lib(?:$|/(?!api/tunnels(?:[.]rb)?$))`、のちに`lib-askgk-api.conf`）。本体の`SPEC.cloudflare-workers-github-oauth-1.20261113.lib-access-control.md`は、これを「公開Apacheの例外」として書いている。
- ところが、この例外は本体のmainの履歴に見当たらない。`containers/demo/apache-demo.conf`の変更は[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62)が最後で、`git log --all -S`でも例外の正規表現・`lib-askgk-api.conf`は出てこない（2026-11-18確認）。今回のイメージのvhostはmainと同じで、例外が無い。例外がどこから入っていたか（未コミットの作業ツリーから作ったイメージなど）は未確認。
- そのため、今回はlib側の`claude/ops/apache-lib-tunnels.conf`に同じ例外を足した。`/lib`のほかのパスの拒否（管理者専用）は変えていない。
- **根本の対処の提案**: 例外を本体の`containers/demo/apache-demo.conf`（または`lib-askgk-api.conf`をコミットしてDockerfileで置く）に入れ、テストで固定する。イメージを作り直すたびに例外が消える状態を、イメージ側で直す。lib側の例外は、それまでのつなぎになる。

#### 根拠

- 本体のコミット[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62)（2026-11-11）「本体コンテナでlibのSSI・CGIを、管理者だけが本体ワーカー経由で見られるようにする」と、その親での`apache-demo.conf`（`/debug`・`/admin`だけを拒否）。
- 本体`SPEC.cloudflare-workers-github-oauth-1.20261113.lib-access-control.md`（入口ごとの制御、tunnels APIの例外）、`SPEC.cloudflare-workers-github-oauth-1.20261115.lib-access-via-worker.md`（2つの入口）。
- lib`NOTICE.lib.20261113.lib-admin-only-impact.md`（制限で止まった機能、起動オプションの方針）、このNOTICEの2026-11-13・14の節（署名なしが401から403に変わったこと）。
- 「制限の前」のSSIの行は、親コミットの`apache-demo.conf`と、[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62)で`apache-lib.conf`・`server.js`の`/lib`の中継が新しく足されたことからの判断。2026-11-10以前に、公開側から`/lib/*.shtml`が実際に開けたかは確かめていない。

### tree-viewのワーカータブが真っ白になる（2026-11-18）

- **原因**: ワーカータブは、dynamicneko → 本体の中継（`/api/tree-view/conversation-stream-external/lib/*`）→ `server.js` → 内部Apache 8445を通る。8445（`010-lib.conf`）に会話ストリームの中継が無く、`conversation-embed.html`はストリームのサーバーが作るページではなく静的なファイルのまま返り（CSPのnonce・資産のticketなし）、最初に呼ぶ`/lib/api/chat/session`が404だった。2026-11-13の修正が前提にした中継は、本体の作業ツリーの未コミットの変更のままで、11-13以降のイメージに入っていなかった。
- **このコンテナでの対処**: 本体PR nekoserver/cloudflare-workers-github-oauth-1#2660 の`containers/demo/apache-lib.conf`を`/etc/apache2/sites-available/010-lib.conf`に置き、`apache2 -t`の後に`apache2 -k graceful`で読み直した。元の設定は、mainの`apache-lib.conf`と同じ。
- **確かめたこと**: `server.js`（8080）経由で、`conversation-embed.html`がストリームのサーバーのログインのページ（`frame-ancestors`にdynamicnekoを含む）になり、署名付きの観測セッションの発行が200、SSEで`conversation`（40件）を受信した。askgk（8443）の`claude_prompt`も引き続き`done`。
- **確かめていないこと**: 利用者のブラウザでのワーカータブの表示。本体の中継を通るWebSocket（`server.js`がupgradeを中継しないため、届かない見込み。SSEで表示できる）。
- **注意**: この置き換えはコンテナを再起動すると消える。本体PR #2660をマージしてイメージを作り直すまでは、再起動のたびに同じ置き換えが要る。
