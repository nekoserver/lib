# SPEC: libリポジトリの現状（2026-11-18、opus-5.5）

作成日: 2026-11-18（UTC）
作成: opus-5.5（Claude Opus 5.5、Claude Code）
対象: `nekoserver/lib` の `main`（`14e82cb`、PR #156のマージ後）と、本体のdemoコンテナ（`mygw.nekomaneki.work`、トンネル`nekoroot`）での動作
状態: 現状の記録。既存のSPECを読み、2026-11-18に実物で確かめ直した内容で書き出した。設定・コードは変えていない。
評価: [`EVAL.lib.20261118.opus-5.5.md`](EVAL.lib.20261118.opus-5.5.md)

各要件には番号（`REQ-…`）を付ける。EVALはこの番号ごとに充足・未充足・未確認を記録する。詳細を定める既存のSPECがある項目は、そのSPECを正とし、ここでは要点と現状だけを書く。

---

## 1. 位置づけと、既存のSPEC

**対象**: libリポジトリにあるSPECの一覧 — どの範囲を、どのSPECが定めるか。

libは、Apacheの`/lib`に置くページ・CGI・API（tunnels API、AIチャットのストリーム、Museのダッシュボードなど）と、それを動かすコンテナの中の常駐プロセス（LLM worker・会話observer・ストリームのサーバー）をまとめたリポジトリ。

| SPEC | 範囲 | 現状との関係 |
|---|---|---|
| [`SPEC.lib.20261118.lib-features-access.md`](SPEC.lib.20261118.lib-features-access.md) | `/lib`の入口（A〜D）、機能ごとの認証、制限の層 | 入口と制限の層は今も正しい。**7章（bind mountなし、8445に中継なし）は、同日のPR #155・#156の後は古い**（本書3章） |
| [`claude/SPEC.claude.20261102.md`](claude/SPEC.claude.20261102.md) | Claude Code環境で動かす別名版（`tunnels.claude.rb`・worker・observer・復元） | 中心は正しい。復元の手順は本書4章の5段が今の形 |
| [`SPEC.lib.20261028.spec-eval.md`](SPEC.lib.20261028.spec-eval.md) | tree-viewからのSPEC評価（`ops/spec_eval.py`） | SPECとEVALの対応（同じディレクトリ、`EVAL`＋同じ接尾辞）は本書と本書のEVALにも当てはめる |
| [`SPEC.lib.20261104.console-stream-adhoc.md`](SPEC.lib.20261104.console-stream-adhoc.md) | mygwストリームへの投稿（同じ会話への一本化） | 変更なし |
| [`SPEC.lib.20261111.muse-tailnet-lessons.md`](SPEC.lib.20261111.muse-tailnet-lessons.md) | Museへの経路で先に決めること | 変更なし |
| [`muse/SPEC.md`](muse/SPEC.md)、[`muse/SPEC.scripts.md`](muse/SPEC.scripts.md) | Museの実行経路（受付・承認・実行）、読み取り用スクリプト・受信側 | 本書6章 |
| [`SPEC.ipv6range.20260217.md`](SPEC.ipv6range.20260217.md) | `ipv6range.shtml` | 変更なし |

- **REQ-DOC-1**: 既存のSPECと食い違う現状は、本書に「どのSPECの、どこが古いか」を書く。既存のSPECを黙って書き換えない。

---

## 2. 入口と制限

**対象**: `/lib`に届く経路 — 入口ごとに、誰が通れるか。詳細は`SPEC.lib.20261118.lib-features-access.md`の1・4章。

| 入口 | 経路 | 誰が通れるか |
|---|---|---|
| A. 公開 | Cloudflare → cloudflared（`nekoroot`）→ Apache :8443（`000-demo.conf`） | `/lib`・`/debug`・`/admin`は403。例外は`/lib/api/tunnels`（署名ヘッダー付き）と、起動オプションのときのチャットの経路 |
| B. 管理者 | 本体ワーカー`/cf-containers/proxy/lib/...` → `server.js` :8080 → 内部Apache `127.0.0.1:8445`（`010-lib.conf`） | 本体ワーカーにログインした管理者 |
| C. 所有者 | dynamicneko → 本体ワーカーの受信ルート → `server.js` → 8445 | dynamicnekoの所有者（会話の中継に限る） |
| D. コンテナの中 | loopback（8091・8092）、unixソケット（worker・observer） | コンテナの中のプロセス |

- **REQ-ACC-1**: 公開側（8443）は、`/lib`・`/debug`・`/admin`を一律に403にする。
- **REQ-ACC-2**: 公開側の`^/lib/api/tunnels$`だけは、`X-Timestamp`と`X-Signature`の両方があれば通す。署名なしは403、不正な署名は401（CGI）、`/lib/api/tunnels/extra`などの別のパスは403。
- **REQ-ACC-3**: AIチャットの経路（`/lib/conversation-embed.html`・`/lib/chat/`・`/lib/t/`・`/lib/api/chat/*`）は、起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ、経路ID付きの要求を公開側から通す。それ以外は403。
- **REQ-ACC-4**: 内部Apache（8445）は`127.0.0.1`だけで待ち受け、`/var/www/html/lib`は`Require local`。
- **REQ-ACC-5**: 入口を通った後の認証は各機能が行う（`SPEC.lib.20261118.lib-features-access.md`の3章）。tunnels APIの`message`・`ask_id`・LLMへの要求はHMAC署名が必須。

---

## 3. 配置（2026-11-18の現状）

**対象**: `/var/www/html/lib`と内部Apacheの今の形 — `SPEC.lib.20261118.lib-features-access.md`の7章から変わった点。

| 項目 | 11-18のSPECの7章 | 今（PR #155・#156の後、コンテナ再起動後） |
|---|---|---|
| `/var/www/html/lib` | bind mountされていない。`restore-claude-host.sh`が複製した一部だけ | **`/root/lib`のbind mount**（`findmnt`: `/dev/vdc[/root/lib]`）。リポジトリ全体が見える |
| 8445のチャットの中継 | 無い | **`010-lib.conf`にある**（イメージの側、または`apache-lib-internal-chat.conf`）。`/lib/api/chat/ws`は8091、`/lib/api/chat/`・埋め込みページ・`/lib/chat/`・`/lib/t/`は8092 |
| 8445の拒否の表（`/lib/ops`・`test`・`keys`、`.py`・`.md`など） | 無い | 無いまま（本体SPEC 2026-11-13が書いている拒否は、まだイメージに入っていない） |

- **REQ-DEP-1**: `/var/www/html/lib`が`/root/lib`のbind mountのときは、復元はファイルを複製しない（自分自身への複製で失敗するため）。bind mountでなければ、`api`・`claude/api`・`ops/*.py`・`chat`・`conversation-embed.html`を複製する。
- **REQ-DEP-2**: 8445がチャットの中継を持たないときだけ、復元が`apache-lib-internal-chat.conf`を足す。持っていれば何もしない。
- **REQ-DEP-3**（目標、未実現）: 8445でも、リポジトリの管理用のファイル（`.git/`、ソース、文書、テスト）を返さない。本体SPEC 2026-11-13の拒否の表をイメージに入れて実現する。入るまでは、管理者（入口B）から見えることを既知の状態として扱う。

---

## 4. 復元（`claude/ops/restore-claude-host.sh`）

**対象**: コンテナの起動後に、rootで1回実行する復元 — 何をして、何度実行してもよいか。

| 段 | 内容 | 要件 |
|---|---|---|
| 1 | `/var/www/html/lib`の用意（REQ-DEP-1） | — |
| 2 | `/etc/apache2/lib-secrets.conf`（0600）に`ORIGIN_HMAC_SECRET`とCloudflareのトークン（`LIB_TUNNELS_CF_TOKEN`、無ければ`CF_CONTAINER_API_TOKEN`）を書く | REQ-RST-2 |
| 3 | `lib-tunnels.conf`（tunnels APIのCGIと公開側の例外）・`lib-chat.conf`（チャットの経路）を置き、vhostにIncludeする。起動オプションが`1`なら`lib-chat-route-access.conf`を置き、そうでなければ消す。8445の中継（REQ-DEP-2） | REQ-RST-3 |
| 4 | `a2enmod headers`、`apache2ctl configtest`、Apacheの起動または`graceful`、8443の待ち受けの確認。worker・observer・ストリームのサーバーの起動（元のworker・observerは止める） | REQ-RST-4 |
| 5 | 本体リポジトリのClaude Codeのhooksの復元（`restore-claude-hooks.sh`）。失敗しても1〜4は戻さない | REQ-RST-5 |

- **REQ-RST-1**: 何度実行してもよい。Includeを重ねない。動いている常駐プロセスは起動し直さない。
- **REQ-RST-2**: 秘密の値はリポジトリの外（0600のファイル）にだけ書く。
- **REQ-RST-3**: tunnels APIのIncludeは、vhostの`ProxyPass /`・イメージの`ScriptAliasMatch`・`lib-askgk-api.conf`のIncludeより前に置く。チャットのIncludeは`RewriteEngine On`の直後に置く。
- **REQ-RST-4**: Apacheは`apache2ctl`ではなく`/usr/sbin/apache2 -k`で操作する（このコンテナでは`apache2ctl`がsystemctlへ渡し、何もしないで0を返すため）。
- **REQ-RST-5**: hooksの復元は、本体リポジトリの`node_modules`が無い（または壊れたsymlink）ときだけ`npm ci`し、`.claude/settings.json`にある各hookのスクリプトが存在して`node --check`を通ることを確かめる。hookのスクリプトは実行しない。
- **REQ-RST-6**: `LIB_ROUTE_ACCESS_CONTROL`は起動オプション。復元を手で実行し直すときは、今の状態（`/etc/apache2/lib-chat-route-access.conf`の有無）と同じ値を渡す。渡し忘れると、チャットの経路の例外が外れる。

---

## 5. tunnels API

**対象**: `/lib/api/tunnels`（`claude/api/tunnels.claude.rb`）— Slackの`/neko askgk`の受け口。詳細は`claude/SPEC.claude.20261102.md`の「tunnels.claude.rb」。

- **REQ-TUN-1**: 署名付き`GET`で、Cloudflareから取ったトンネル一覧（`tunnels`・`auth`・`fetched_at`）をJSONで返す。
- **REQ-TUN-2**: エンジンの先頭が無い`message`はClaudeへ送り、その要求で取ったトンネル一覧をプロンプトに添える。応答は`ask_status`・`ask_id`・`reply`・`via`・`llm_model`。
- **REQ-TUN-3**: `ask_id`で、後から同じ回答を引ける。
- **REQ-TUN-4**: `message`付きの待ちは最大300秒。ApacheのCGIのタイムアウトは330秒。

トンネルの期待状態（運用）: `nekoroot`はhealthy、`cfc-tunnel`はdown（2026-10-22にユーザー確認、`cf-container/SETTING.cf-container.md`）。`term-root`は2026-11-07から一覧にある。`cfc-tunnel`のdownは障害として扱わず、起動しない。

---

## 6. Muse（`lib/muse`）

**対象**: Museのダッシュボード・読み取り用スクリプト・実行経路。詳細は`muse/SPEC.md`・`muse/SPEC.scripts.md`。

- **REQ-MUSE-1**: ダッシュボードのSSIが直接実行するスクリプトは、gitで`100755`にする（`muse/SPEC.scripts.md`の1章）。シェバンのあるファイルはすべて実行権限を持つ（`test/muse_scripts_test.py`の`ScriptRulesTest`）。
- **REQ-MUSE-2**: 読み取り用スクリプトは状態を変えず、tailscaleのCLIを呼ばず、loopback・unixソケットの外へ出ない。
- **REQ-MUSE-3**: 実行は、受付 → 承認待ち → ホストでの承認 → 診断ゲート → 1ターンの順だけ。Webに承認の手段を置かない（`muse/SPEC.md`）。

---

## 7. リポジトリの約束（`CLAUDE.md`）

**対象**: 変更のたびに守ること — `CLAUDE.md`の各節の要点。

- **REQ-REPO-1**: ユーザーの承認なしに、環境変数・シークレット・設定スイッチを足さない。
- **REQ-REPO-2**: テストファースト。テストが失敗したままpush・デプロイしない。報告では、テストで確かめたこと・実物で確かめたこと・確かめていないことを分ける。
- **REQ-REPO-3**: Museに関わる変更は`muse/NOTICE-TO-MUSE.md`に書き足す。コンテナを変えたら`CONTAINERS.md`を直す（どちらもテストが形を検査する）。
- **REQ-REPO-4**: PRはGitHub Web API（curl）で作る。`.github_token`はコミットしない。

---

## 8. テスト

**対象**: 自動テストと、その実行のしかた。

| 種類 | 実行 | 範囲 |
|---|---|---|
| Python（lib） | `PYTHONPATH=ops python3 -m unittest discover -s test -p '*_test.py'` | ストリーム・observer・worker・セッション・Muse・CONTAINERS.mdなど。`*_live_test.py`は実物のMuseが要り、無ければskip |
| Python（lib/claude） | `cd claude/test && python3 -m unittest discover -p '*_test.py'` | 別名版、Apacheの設定（使い捨てのApache）、復元、hooks、stream_routes |
| Ruby | `ruby test/<名前>_test.rb`、`ruby claude/test/tunnels_claude_rb_test.rb` | llm_prompt・railway_exec・tunnels・hmac_auth |
| Node | `node --test test/*_test.mjs` | ブラウザ側のモジュール（チャット） |

- **REQ-TEST-1**: 上の4種類がすべて通ること。環境の不足（コマンドの場所、gemの版）による失敗は、コードの失敗と分けて記録する。

---

## 9. 確かめていないこと

- 入口B（本体ワーカーから）・入口C（dynamicneko経由）を実際に通した結果。本書の8445の結果は、コンテナの中から直接送ったもの。
- Slackからの`/neko askgk`（Cloudflare Worker → rust-worker-sqlx-d1 → tunnels API）。
- `cfc-tunnel`が2026-11-18 13:33:09 UTCに切断した記録（`conns_inactive_at`）の接続元。このコンテナには`cfc-tunnel`の接続用トークンが無い。
- コンテナの再作成後に、本書の状態が復元の1回の実行で戻ること（今回は起動済みのコンテナで実行し直しただけ）。
