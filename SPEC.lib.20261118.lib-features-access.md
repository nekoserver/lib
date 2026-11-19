# SPEC: libに割り当てている機能と、入口ごとの制限（2026-11-18）

作成日: 2026-11-18（UTC）
状態: 現状の記録。設定・権限は変えていない（同日のtunnels APIの例外の修正を除く。6章）。
改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。bind mountと8445の中継が入った後の状態で、2章の8445の列と7章を測り直した。要件の番号（`REQ-LA-…`）を8章に足した。改訂の内容は末尾の「改訂の記録」
評価: [`EVAL.lib.20261118.lib-features-access.opus-5.5.20261119.md`](EVAL.lib.20261118.lib-features-access.opus-5.5.20261119.md)
定期的な見直し: このSPECは[`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す

関連: [`NOTICE.lib.20261107.claude-host-setup.md`](NOTICE.lib.20261107.claude-host-setup.md)の2026-11-18の節（制限の目的と、制限の前の状態）、[`NOTICE.lib.20261113.lib-admin-only-impact.md`](NOTICE.lib.20261113.lib-admin-only-impact.md)（制限で止まった機能）、[`SETTINGS.claude-host.20261102.md`](SETTINGS.claude-host.20261102.md)（復元の手順）。本体リポジトリの`SPEC.cloudflare-workers-github-oauth-1.20261113.lib-access-control.md`・`SPEC.cloudflare-workers-github-oauth-1.20261115.lib-access-via-worker.md`。

---

## 1. 入口

**対象**: 本体のdemoコンテナ（`mygw.nekomaneki.work`、トンネル`nekoroot`）で`/lib`に届く経路 — 誰がどこを通って`/lib`に届くかを、入口ごとに分ける。

| 入口 | 経路 | 誰が通れるか | 主な設定 |
|---|---|---|---|
| A. 公開 | `https://mygw.nekomaneki.work/lib/...` → Cloudflareのエッジ → cloudflared → Apache :8443（`000-demo.conf`） | 原則だれも通れない（403）。例外は2章の表のとおり | vhostの`<LocationMatch "^/(?:debug|admin|lib)(?:/|$)">`の`Require all denied` |
| B. 管理者（本体ワーカー経由） | 本体ワーカー`/cf-containers/proxy/lib/...` → Durable Object → `server.js` :8080 → 内部Apache `127.0.0.1:8445`（`010-lib.conf`） | 本体ワーカーにログインした管理者だけ | ワーカーの`authMiddleware`・`cfDashboardAdminMiddleware`、内部Apacheの`Require local` |
| C. 所有者（dynamicneko経由） | dynamicneko `/lib/*` → 本体ワーカーの専用受信ルート → `server.js` → `127.0.0.1:8445` | dynamicnekoの所有者だけ（会話の中継に限る） | 所有者ログイン、PWAセッション、origin、Worker署名、短寿命トークン（本体SPEC 2026-11-13） |
| D. コンテナの中 | `127.0.0.1:8091`（WebSocket）・`127.0.0.1:8092`（HTTP）・`/run/lib-codex/worker.sock`・`/run/lib-chat-observer/observer.sock`、CGIの直接実行 | コンテナの中のプロセス（root・`www-data`など） | loopback・unixソケットだけで待ち受ける。各サーバーが独自に認証する（3章） |

Aの例外の判定はApacheの段で終わる。署名が正しいかなどの中身は、A〜Dのどこから来ても各機能が自分で確かめる（3章）。

---

## 2. 機能と、入口ごとの扱い

**対象**: `/root/lib`の中で、Apacheから見える機能 — 何が置かれ、どう動き、入口A・Bでどう扱われるか。

「8443」「8445」の列は、コンテナの中から`GET`を送った実測（8443は`https://127.0.0.1:8443`、8445は`http://127.0.0.1:8445`）。8443は2026-11-18、8445は2026-11-19に測り直した値（`/root/lib`のbind mountと8445の中継が入った後）。11-18の8445の値は末尾の「改訂の記録」。

| パス | 機能 | 動き方 | 機能自体の認証 | A. 公開（8443） | B. 管理者（8445） |
|---|---|---|---|---|---|
| `/lib/api/tunnels` | tunnels API。Slackの`/neko askgk`の受け口。トンネル一覧と`◯_prompt="△"`（claude・codex・muse・nemotron）の振り分け | CGI（`claude/api/tunnels.claude.rb`）→ LLM worker | HMAC署名（`X-Timestamp`・`X-Signature`）。一覧だけならIP許可も可 | **例外**: 署名ヘッダーがあれば通す。無ければ403、不正な署名は401（CGI） | **200（`tunnels.rb`のソースを文字のまま返す。`api/tunnels`は`tunnels.rb`へのsymlinkで、CGIとして実行されない）**（11-19も同じ） |
| `/lib/conversation-embed.html`、`/lib/chat/`、`/lib/t/<ID>/` | AIチャットのパネル・tree-viewのワーカータブの埋め込みページと資産 | `chat_http_stream.py` :8092へ中継 | ログインのフォーム、観測セッション（HMAC、最長7日）、`frame-ancestors` | 403。起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ、経路ID付きの要求を通す（4章） | 401（中継され、ストリームのサーバーがログインを求める）。`/lib/chat/`も401 |
| `/lib/api/chat/{session,sse,ndjson,jsonseq,console,…}` | ストリーム（SSE・NDJSON・JSON Text Sequence）、セッションの発行、consoleへの送信 | :8092へ中継 | HMAC署名、または観測・投稿のセッション。投稿セッションは15分〜7日 | 同上 | `session`は403（中継され、ストリームのサーバーがOriginの無い要求を`origin_rejected`で断る） |
| `/lib/api/chat/ws` | WebSocketのストリーム | `chat_websocket.py` :8091へ中継 | nonceへのHMAC、またはセッション | 同上 | 426（Upgradeの無い`GET`。中継されている） |
| `/lib/*.shtml`（`date`・`ls`・`printenv`・`ip`・`checkip`・`which_gh`・`gh_repo_list`・`ruby_-v`など） | コンテナの中でコマンドを実行し、出力をそのまま表示する | SSIの`#exec cmd=` | なし（入口の制限だけが頼り） | 403 | **200（`date.shtml`・`printenv.shtml`。コマンドが実行される）** |
| `/lib/*.cgi`（`github-hook`・`oauth-token`・`tunnels`・`ruby-calendar`） | GitHubのwebhook、OAuthトークンの取得、旧tunnels、カレンダー | CGI（SSIの`#exec cgi=`からも呼ぶ） | 個別。`oauth-token.cgi`はPOSTの中身だけを見る | 403 | 200（`github-hook.cgi`・`oauth-token.cgi`） |
| `/lib/muse/dashboard/*.shtml`、`ask.cgi` | Museのダッシュボード（状態・ジョブ・ポート・tailnetなど）。実行系は受付だけ | SSIで`muse/*.sh`を呼ぶ。`ask.cgi`は受付だけで、実行は受ける側のホストでの承認が要る | 読み取り系はなし。`tailnet-health`は`X-Forwarded-User`で正規ユーザーを照合（2026-11-18） | 403 | `index.shtml`は200。`tailnet.shtml`は`(access denied)`（正規ユーザーのフラグが無い）。`ask.cgi`の`GET`は500 |
| `/lib/keys/` | SSHの公開鍵を登録するページ（`register.rb`） | CGI | HMAC必須（`HmacAuth.enforce!`、`require_hmac: true`） | 403 | 200 |
| `/lib/ops/*.py` | worker・observer・ストリームのサーバーのソース | 静的なファイル（実行するのはrootのプロセス） | — | 403 | **200（ソースが読める）** |
| `/lib/CLAUDE.md`などの文書、`/lib/test/` | 文書・テスト | 静的なファイル | — | 403 | **`/lib/CLAUDE.md`・`/lib/.git/config`は200**。`/lib/test/`は403（一覧の禁止） |
| `/debug`、`/admin` | `server.js`の診断（ログ・通信の調査） | `server.js` :8080 | — | 403（2026-10-27から） | Bの入口（`/cf-containers/proxy/...`）からだけ |

---

## 3. 機能ごとの認証

**対象**: 入口を通った後に各機能が行う確認 — Apacheの制限とは別に、機能自体が誰を受け付けるか。

| 機能 | 確認すること | 失敗したとき | 鍵・設定 |
|---|---|---|---|
| tunnels API（CGI） | HMAC-SHA256（`METHOD\nREQUEST_URI\nUNIX秒\nSHA256(body)`）、時刻差300秒以内。`message`・`ask_id`・LLMへの要求は署名が必須。一覧だけはIP許可でも可 | 401 `hmac_required`など | `ORIGIN_HMAC_SECRET`（`/etc/apache2/lib-secrets.conf`、0600） |
| LLM worker | `engine`が`codex`・`claude`・`muse`のどれか。プロンプトは空でなく16,384バイト以下 | `unsupported_engine`（nemotronなど）、`empty_prompt`、`prompt_too_large` | Claudeは`codex-web`の認証、Museは起動時の`MUSE_API_KEY`（実行環境から取り除く） |
| ストリーム（:8092、:8091） | originが`LIB_CHAT_ORIGINS`にあること。送信はHMAC署名、観測はセッション。ソケットへの`submit`は`engine`の許可リスト | 403 `origin_rejected`、401 `authentication_failed`、400 `invalid_request` | `ORIGIN_HMAC_SECRET`、`LIB_CHAT_ORIGINS` |
| consoleへの送信 | 投稿セッションの署名と、サーバーの稼働中セッション表への登録 | 401 `console_session_required`、409 `console_in_use` | 同上 |
| Museのダッシュボードの実行系 | `ask.cgi`は受付だけ。受ける側のホストのシェルで`sdk-approve.sh`による承認 | 承認されなければ実行されない | — |

---

## 4. 制限の層

**対象**: `/lib`への要求に順にかかる制限 — どの段で、何を根拠に止めるか。

| 順 | 段 | 内容 | 置き場所 | 根拠 |
|---|---|---|---|---|
| 1 | 公開Apacheの拒否 | `/debug`・`/admin`・`/lib`を一律に403 | `000-demo.conf`（本体`containers/demo/apache-demo.conf`） | 利用者の判断「管理者だけ」（2026-11-11）、本体[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62) |
| 2 | tunnels APIの例外 | `^/lib/api/tunnels$`だけ、`X-Timestamp`と`X-Signature`の両方があれば通す | lib`claude/ops/apache-lib-tunnels.conf`（vhostの拒否の後でInclude） | 本体SPEC 2026-11-13「公開Apacheの例外」。6章 |
| 3 | AIチャットの経路の例外（任意） | 起動オプションが`1`のときだけ、経路ID（`?via=`の`treeview-worker`・`aichat-panel`・`health`、Cookie`lib_chat_via`）のある要求をチャットの4経路に通す。記録は`/var/log/apache2/lib-chat-via.log` | lib`claude/ops/apache-lib-chat.conf`・`apache-lib-chat-route-access.conf` | 利用者の方針（2026-11-13）、PR #147 |
| 4 | 管理者の確認 | 本体ワーカーへのログインと管理者の確認 | 本体ワーカー`/cf-containers/proxy/*` | 本体SPEC 2026-11-15 |
| 5 | 内部Apacheの制限 | `127.0.0.1:8445`だけで待ち受け、`/var/www/html/lib`は`Require local`、それ以外は拒否 | `010-lib.conf`（本体`containers/demo/apache-lib.conf`） | 本体[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62) |
| 6 | 機能自体の認証 | 3章の表 | 各CGI・サーバー | — |

---

## 5. 変更の経緯

**対象**: `/lib`の制限が今の形になるまでの変更 — いつ、何が変わったか。

| 日付 | 変更 | 影響 |
|---|---|---|
| 2026-10-27 | 公開側で`/debug`・`/admin`を拒否（本体[`4fde15d1`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/4fde15d1)） | 診断は管理者の入口からだけ |
| 2026-11-02〜 | `restore-claude-host.sh`が8443に、tunnels APIのCGIとAIチャットの経路を入れる | どちらも公開側から届き、各機能の認証だけで守られていた。署名なしのtunnels APIは401 |
| 2026-11-11 | 公開側で`/lib`を拒否し、管理者の入口（ワーカー → 8445）を新設（本体[`1a9e0c62`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/1a9e0c62)） | SSIのページが公開側から見えなくなる。askgkとAIチャットも巻き込まれて403 |
| 2026-11-13 | イメージ側にtunnels APIの例外。チャットの経路は起動オプションのときだけ通す方針（PR #147） | askgkが戻る。署名なしは403。AIチャットは既定で403のまま |
| 2026-11-14 | イメージの例外が`lib-askgk-api.conf`のIncludeに移る | `restore-claude-host.sh`のInclude位置を直した |
| 2026-11-18 | 今回のイメージにtunnels APIの例外が無い（本体のmainの履歴にも無い） | askgkが再び403。lib側の`apache-lib-tunnels.conf`に例外を足して直した（6章） |

---

## 6. 2026-11-18の修正

**対象**: `claude/ops/apache-lib-tunnels.conf`と`claude/test/apache_lib_tunnels_test.py` — 公開側のtunnels APIの例外を、lib側の設定に持たせる。

| ファイル | 変更 |
|---|---|
| `claude/ops/apache-lib-tunnels.conf` | `<LocationMatch "^/lib/api/tunnels$">`に`Require expr "-n %{HTTP:X-Timestamp} && -n %{HTTP:X-Signature}"`を足した |
| `claude/test/apache_lib_tunnels_test.py`（新規） | 使い捨てのApacheに、今のvhostと同じ拒否とこの設定を入れて確かめる。署名ヘッダー付きはCGIに届く、無ければ403、`/lib/api/tunnels/extra`・`/lib/api/tunnels.rb`・`/lib/ip.shtml`は403。修正前は403で失敗することを確かめた |

`restore-claude-host.sh`の再実行で反映した。Apache経由の結果は、署名付きの`claude_prompt`・`muse_prompt`が`done`、署名なし403、不正な署名401、`/lib`のほかのパス403。

本体のイメージにこの例外を入れれば、lib側の例外は要らなくなる（提案、未実施）。

---

## 7. 確かめたこと・確かめていないこと

**対象**: この記録の根拠の範囲。

確かめたこと（2026-11-18）:

- 2章の8443・8445の列（コンテナの中からの`GET`）。`server.js` :8080への`GET /lib/date.shtml`は404。
- 有効なApacheの設定（`000-demo.conf`・`010-lib.conf`・`lib-tunnels.conf`・`lib-chat.conf`）と、本体のmainの`apache-demo.conf`が同じであること。
- **`/var/www/html/lib`はbind mountされていない。** 本体の`entrypoint.sh`は`/root/lib`をbind mountするはずだが、今は`restore-claude-host.sh`が複製した一部（`api`・`claude/api`・`ops/*.py`・`chat`・`conversation-embed.html`）だけがある。そのため、Bの入口からもSSIのページ・Museのダッシュボード・`keys`は404になる。
- **今の`010-lib.conf`には、本体SPEC 2026-11-13が書いている拒否の表（`/lib/ops`・`test`・`keys`、`.py`・`.md`などの拒否）と、チャットの中継が無い。** そのため、Bの入口から`/lib/ops/*.py`と`/lib/api/tunnels`（`tunnels.rb`）のソースが読める（管理者だけ）。本体SPEC 2026-11-13にある`ScriptAliasMatch`（`/lib/api/tunnels`を固定のCGIへ）も無い。チャットの中継は、本体の`containers/demo/apache-lib.conf`に2026-11-18に足した（ソースのみ。イメージの再ビルドとコンテナの再起動で反映。本体SPEC`…muse-request-routes.md`の「経路3」）。

### 2026-11-19に測り直したこと（改訂）

- **`/var/www/html/lib`は`/root/lib`のbind mount**（`findmnt`: `/dev/vdc[/root/lib]`）。本体のentrypointが`/root/lib`を待ってからmountする（本体`containers/demo/lib-restore-wait.sh`、2026-11-18）。上の「bind mountされていない」は11-18の時点の記録で、今は当てはまらない。
- **8445にチャットの中継がある**（イメージの`010-lib.conf`。`restore-claude-host.sh`は「already relays」と判断して何も足していない）。
- その結果、Bの入口（管理者）から、SSIのページ（コマンドの実行を伴う）・CGI・Museのダッシュボード・`keys`・ソース・文書・`.git/config`が開ける。本体SPEC 2026-11-13の拒否の表（`/lib/.git`・`/lib/ops`・`/lib/test`、`.py`・`.md`など）は、まだイメージに入っていない。管理者だけが通れる入口なので公開ではないが、目標の状態（8章のREQ-LA-6）とは食い違う。
- 公開側（8443）は11-18と同じ: 2章のすべてのパスが403。例外のtunnels APIは署名なし403・不正な署名401・署名付き200、チャットの経路は`?via=aichat-panel`の埋め込みページだけが401（アプリに届く）、`?via=bogus`・経路IDなしは403。

確かめていないこと:

- bind mountされていない理由（コンテナの起動時に`/root/lib`が無かったのか、mountが失敗したのか）。起動のログの場所を確かめていない。
- Bの入口を、本体ワーカーから実際に通した結果（今回はコンテナの中から8445へ直接送っただけ）。
- Cの入口（dynamicneko経由）の今の動作。
- `/lib/*.cgi`・`/lib/api/chat/ws`の8445での応答。
- 2026-11-13・14のイメージの例外が、どこから入っていたか。
- Slackからの`/neko askgk`（修正後）。

---

## 8. 要件の番号（2026-11-19に付与）

| 番号 | 要件 | 本書の章 |
|---|---|---|
| REQ-LA-1 | 公開側（8443）は`/debug`・`/admin`・`/lib`を一律に403にする | 1・4 |
| REQ-LA-2 | 公開側の`^/lib/api/tunnels$`だけは、`X-Timestamp`と`X-Signature`の両方があれば通す。署名の照合はCGI | 4・6 |
| REQ-LA-3 | AIチャットの経路は、起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ、経路IDのある要求を通す | 4 |
| REQ-LA-4 | 内部Apache（8445）は`127.0.0.1`だけで待ち受け、`/var/www/html/lib`は`Require local` | 1・4 |
| REQ-LA-5 | 入口を通った後の認証は各機能が行う（3章の表） | 3 |
| REQ-LA-6（目標、未実現） | 8445でも、リポジトリの管理用のファイル（`.git/`、ソース、文書、テスト）と、コマンドを実行するSSIを返さない。本体SPEC 2026-11-13の拒否の表をイメージに入れて実現する | 7 |

---

## 改訂の記録

| 日付 | モデル | 箇所 | 11-18の版 | 改訂後 | 根拠 |
|---|---|---|---|---|---|
| 2026-11-19 | opus-5.5 | 2章の8445の列 | 埋め込みページ200・`/lib/chat/`403・`session`404・`ws`未測定・SSI404・CGI未測定・Muse404・`keys`404・文書404 | 401・401・403・426・200・200・200（`ask.cgi`は500）・200・200（`.git/config`も200） | コンテナの中からの`GET`（2026-11-19） |
| 2026-11-19 | opus-5.5 | 7章 | bind mountなし、8445に中継なし | どちらもある（11-19の節を追加。11-18の記述は残した） | `findmnt`、`/tmp/restore-claude-host.log`の「already relays」 |
| 2026-11-19 | opus-5.5 | 8章 | なし | 要件の番号 | — |
