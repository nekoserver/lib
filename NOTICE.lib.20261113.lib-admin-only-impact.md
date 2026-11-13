# NOTICE: 「libは管理者専用」による影響の範囲

日付: 2026-11-13（UTC）
**対象**: 本体のdemoコンテナ（`mygw.nekomaneki.work`、トンネル`nekoroot`）の公開Apache（:8443） — 2026-11-11の利用者の判断で`/lib`を管理者専用にしたことで、公開側から`/lib`を使っていた機能がどこまで止まっているかの記録。方針そのものは変えない（利用者: 「悪くはない」）。例外は影響の範囲を調べ終え、ポリシーと仕様が固まってから対処する（下の「現状方針」）。

## 方針と現在の設定

- 本体リポジトリ`containers/demo/apache-demo.conf`の`<LocationMatch "^/(?:debug|admin)(?:/|$)|^/lib(?:$|/(?!api/tunnels(?:[.]rb)?$))">`が`Require all denied`。コメントは「lib (SSI, apache-lib.conf) is for administrators only, via the same proxy (user decision 2026-11-11)」。
- 例外は`/lib/api/tunnels`（と`.rb`）だけ。`X-Timestamp`・`X-Signature`の両ヘッダーが無ければApacheが403、あればCGIがHMACを検証する（askgkの403修正、本体の`REPORT.cloudflare-workers-github-oauth-1.ASKGK-403.20261113.md`）。
- 管理者の入口は、管理用プロキシ（:8080、認証あり）から`127.0.0.1:8445`の`apache-lib.conf`（`Require local`）。2026-11-13時点で、本体の作業ツリーに、ここへAIチャットの経路（8091・8092）を足す未コミットの変更がある（別の作業）。
- libの`claude/ops/restore-claude-host.sh`は、vhostが`/lib`を管理者専用にしているとき、AIチャットの経路（`lib-chat.conf`）を入れない（2026-11-13、PR #147）。

## 影響（公開URL `https://mygw.nekomaneki.work`、2026-11-13に実測）

| 経路 | 使っている側 | 公開側の応答 | 影響 |
|---|---|---|---|
| `/lib/conversation-embed.html`、`/lib/chat/*`、`/lib/t/*` | dynamicneko tree-viewの**ワーカータブ**（`src/components/tree-view-conversation-stream.tsx`）、本体`/aichat`のAIチャットのパネル（`src/utils/conversationStreamRoutes.ts`・`containerEndpoints.ts`） | 403 | iframeに「Forbidden」が出て、会話を表示できない（利用者の報告、2026-11-13）。背後のストリームのサーバー（8092）は動いており、直接なら401（ログイン要求）を返す |
| `/lib/api/chat/{session,sse,ndjson,jsonseq}` | 埋め込みページ、本体Workerの台帳`src/data/conversation-stream-routes.json`の各経路 | 403 | セッション取得と、SSE・NDJSON・JSON Text Sequenceの配信がすべて止まる |
| `/lib/api/chat/ws`（WebSocket） | 埋め込みページ | 403 | vhostは`ws://127.0.0.1:8080`への書き換えからこのパスを外しているが、拒否が先に効く |
| `/lib/docker.html`、`/lib/docker-dashboard.{css,mjs}` | 本体Worker`/cf-containers/docker.html`（`src/utils/dockerDashboardProxy.ts`が公開URLから取得して中継） | 403 | Dockerのダッシュボードの画面が取れない（中継側の表示は未確認） |
| `/lib/*.shtml`（`ip.shtml`・`tunnels.shtml`など）、`/lib/github-hook.cgi` | 外部から直接（GitHubのwebhookなど、呼出し元は未確認） | 403 | 管理者の入口（:8445）からだけ使える。方針どおり |
| `/lib/api/tunnels` | Slack `/neko askgk`（本体Worker → rust-worker-sqlx-d1） | 署名ヘッダーなし403、ありでCGIへ（無効な署名は401） | 動く（例外）。署名なしのPOSTは以前の401ではなく403になる |

台帳の他の経路（`mynw`・`stream.test.cfc`・`r9`）は別のコンテナで、今回は測っていない（`mynw`は接続できなかった）。

## 現状方針（利用者、2026-11-13）

例外は、影響の範囲を調べ終え、ポリシーと仕様が固まってから対処する。それまでは例外を足さず、上の表の機能は止まったままとする。下の候補は、仕様を決めるときの材料として残す。

### まだ調べていない範囲

- 台帳の他の経路（`mynw`・`stream.test.cfc`・`r9`）の公開側の応答。`mynw`は2026-11-13に接続できなかった。
- `/lib/*.shtml`・`/lib/github-hook.cgi`を外から呼んでいる側（GitHubのwebhookの設定など）。
- 本体Worker`/cf-containers/docker.html`が403を受けたときの画面。
- 管理者の入口（:8080 → :8445）からのAIチャット・Dockerのダッシュボードの動作（本体の作業ツリーの未コミットの変更が前提）。
- 他のリポジトリ（dynamicneko以外のWorker、muse-monitorなど）から`/lib`を呼んでいる箇所。今回は本体とdynamicnekoの`src`・`public`だけを検索した。

### 仕様を決めるときの候補

- ワーカータブとAIチャットのパネル: `/lib/conversation-embed.html`・`/lib/chat/`・`/lib/t/`・`/lib/api/chat/*`の4経路を拒否から外す。外す経路には独自の認証がある（ログイン画面、HMACのセッション、`frame-ancestors`で埋め込み元を本体Worker・dynamicnekoに限定）。
- Dockerのダッシュボード: 本体Workerが公開URLを経由せず管理者の入口から取る形にするか、例外にする。
- イメージの`apache-demo.conf`を変えた場合、イメージを作り直すまで本番のコンテナには入らない（本体`CLAUDE.md`のルール39）。
