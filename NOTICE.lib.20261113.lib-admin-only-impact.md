# NOTICE: 「libは管理者専用」による影響の範囲

日付: 2026-11-13（UTC）
**対象**: 本体のdemoコンテナ（`mygw.nekomaneki.work`、トンネル`nekoroot`）の公開Apache（:8443） — 2026-11-11の利用者の判断で`/lib`を管理者専用にしたことで、公開側から`/lib`を使っていた機能がどこまで止まっているかの記録。方針そのものは変えない（利用者: 「悪くはない」）。起動オプションで有効にしたときだけ、経路情報をもとにしたアクセス制御を行う（下の「現状方針」）。

## 方針と現在の設定

- 本体リポジトリ`containers/demo/apache-demo.conf`の`<LocationMatch "^/(?:debug|admin)(?:/|$)|^/lib(?:$|/(?!api/tunnels(?:[.]rb)?$))">`が`Require all denied`。コメントは「lib (SSI, apache-lib.conf) is for administrators only, via the same proxy (user decision 2026-11-11)」。
- 例外は`/lib/api/tunnels`（と`.rb`）だけ。`X-Timestamp`・`X-Signature`の両ヘッダーが無ければApacheが403、あればCGIがHMACを検証する（askgkの403修正、本体の`REPORT.cloudflare-workers-github-oauth-1.ASKGK-403.20261113.md`）。
- 管理者の入口は、管理用プロキシ（:8080、認証あり）から`127.0.0.1:8445`の`apache-lib.conf`（`Require local`）。2026-11-13時点で、本体の作業ツリーに、ここへAIチャットの経路（8091・8092）を足す未コミットの変更がある（別の作業）。
- libの`claude/ops/restore-claude-host.sh`は、`lib-chat.conf`をvhostの拒否の後でIncludeする。起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ、経路情報のある要求を通す設定を置く（PR #147）。

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

「libは管理者専用」は保つ。経路の制御と深く関わり単純には片付かないため、無駄に厳格にせず、**起動オプションで有効にしたときだけ**、経路情報をもとにしたアクセス制御を行う。

- 起動オプション: 本体Workerの`wrangler.toml`の`[vars]`の`LIB_ROUTE_ACCESS_CONTROL`。`demoContainer.ts`がコンテナへ渡し、起動処理（本体イメージの`post_install.py`が呼ぶ`restore-claude-host.sh`）が見る。`"1"`のときだけ有効。それ以外・未設定では何も足さず、チャットの経路も拒否のまま。
- 有効なとき: 経路ID（`?via=`の許可リスト`treeview-worker`・`aichat-panel`・`health`と、それを引き継ぐCookie`lib_chat_via`）がある要求だけ、チャットの4経路（`/lib/conversation-embed.html`・`/lib/chat/`・`/lib/t/`・`/lib/api/chat/*`）を通す（`apache-lib-chat-route-access.conf`）。経路情報の無い要求は403。SSI・CGI・`ops`・Dockerのダッシュボードなど他の`/lib`は、オプションに関係なく拒否のまま。
- 経路IDは秘密ではない。経路は独自の認証（ログイン、HMACのセッション、`frame-ancestors`）でも守られている。Muse用のキーは使わない（ブラウザが呼ぶ経路で、キーがURL・ログに出るため。利用者の選択）。
- 記録: オプションに関係なく、チャットの経路への要求を`/var/log/apache2/lib-chat-via.log`に`via=…`で記録する（許可リスト外・指定なしは`unknown`）。
- 経路の制御の仕様が固まったら見直す。

### まだ調べていない範囲

- 台帳の他の経路（`mynw`・`stream.test.cfc`・`r9`）の公開側の応答。`mynw`は2026-11-13に接続できなかった。
- `/lib/*.shtml`・`/lib/github-hook.cgi`を外から呼んでいる側（GitHubのwebhookの設定など）。
- 本体Worker`/cf-containers/docker.html`が403を受けたときの画面。
- 管理者の入口（:8080 → :8445）からのAIチャット・Dockerのダッシュボードの動作（本体の作業ツリーの未コミットの変更が前提）。
- 他のリポジトリ（dynamicneko以外のWorker、muse-monitorなど）から`/lib`を呼んでいる箇所。今回は本体とdynamicnekoの`src`・`public`だけを検索した。

