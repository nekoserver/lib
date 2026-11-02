# 機能一覧: lib/claude

作成日: 2026-11-02

**対象**: `lib/claude`で実現している機能と、それと組み合わせて動く本体Worker（`nekoserver/cloudflare-workers-github-oauth-1`）側の会話ストリームの接続先台帳 — 機能ごとに、内容、元にした実装、最終コミット、日時、確認状況をまとめる。

仕様の詳細は[`SPEC.claude.20261102.md`](SPEC.claude.20261102.md)、評価は[`EVAL.claude.20261102.md`](EVAL.claude.20261102.md)、今後は[`PLAN.claude.20261102.md`](PLAN.claude.20261102.md)。

## 最終コミットについて

`lib/claude`のファイルと、本体Worker側の今回の変更は、**2026-11-02時点ですべて未コミット**。そのため「最終コミット」には次の2つを書く。

- **別名版**: 未コミット。日時はファイルの最終更新時刻（UTC）。コミット後にハッシュへ置き換える。
- **元の実装**: 別名版が読み込む・基にしている元ファイルの最終コミット（`git log -1`）。別名版の動作はこの版を前提にしている。

## 一覧

| # | 機能 | 主なファイル | 別名版の最終更新（未コミット） | 元の実装の最終コミット |
|---|---|---|---|---|
| 1 | tunnels APIの別名版 | `api/tunnels.claude.rb` | 2026-11-02 00:35 | [`9b0bc47`](https://github.com/nekoserver/lib/commit/9b0bc47) 2026-10-24 |
| 2 | `/neko askgk`のClaude応答（LLM worker） | `ops/llm_worker_claude.py`、`ops/claude-helper.sh` | 2026-11-01 23:58 | [`6715fe0`](https://github.com/nekoserver/lib/commit/6715fe0) 2026-10-23 |
| 3 | askgkの待ち時間300秒 | `api/tunnels.claude.rb` | 2026-11-02 00:35 | [`a43268c`](https://github.com/nekoserver/lib/commit/a43268c) 2026-10-15 |
| 4 | 会話observer（表示） | `ops/chat_observer_claude.py` | 2026-11-02 00:11 | [`a9c62d5`](https://github.com/nekoserver/lib/commit/a9c62d5) 2026-10-28 |
| 5 | 会話observer（送信） | `ops/chat_observer_claude.py` | 2026-11-02 00:11 | [`a9c62d5`](https://github.com/nekoserver/lib/commit/a9c62d5) 2026-10-28 |
| 6 | SPEC評価の依頼（spec-eval） | `ops/chat_observer_claude.py` | 2026-11-02 00:11 | [`a9c62d5`](https://github.com/nekoserver/lib/commit/a9c62d5) 2026-10-28 |
| 7 | 起動設定 | `ops/*.service`、`ops/start-llm-worker-claude.sh` | 2026-11-01 23:58 | — |
| 8 | ストリーム接続先の導出（コンテナ側） | `ops/stream_routes.py` | 2026-11-02 00:34 | — （新規） |
| 9 | ストリーム接続先の台帳（本体Worker側） | 本体Worker `src/utils/conversationStreamRoutes.ts` ほか | 2026-11-02（未コミット） | [`f4273a8c`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/f4273a8c) 2026-10-26 |
| 10 | テストと手動確認の手順 | `test/*`、`test/manual/*` | 2026-11-02 00:34 | — |

時刻はUTC。元の実装のコミット日時はコミッターの日時（`%cI`）。

## 1. tunnels APIの別名版

**対象**: `lib/claude/api/tunnels.claude.rb` — 本番の配置（rbenvのRuby、表形式の`cf`出力）がないホストで、トンネル一覧のJSON/HTML APIを動かす。

- shebangはPATH上のruby。`cf tunnels list --json`で取得し、接続数が整数で返る形式に対応する。
- 認証（HMAC・IP許可）、絞り込み（`status`・`name`）、`format=html`、`message`・`ask_id`は`tunnels.rb`と同じ。共通処理は`lib/api/tunnels_lib.rb`を読み込む。
- CGIとして直接実行されたときだけ処理し、テストからは読み込みだけができる。
- 元: `api/tunnels.rb`（[`ab73bc3`](https://github.com/nekoserver/lib/commit/ab73bc3) 2026-10-01）、`api/tunnels_lib.rb`（[`9b0bc47`](https://github.com/nekoserver/lib/commit/9b0bc47) 2026-10-24 fix: respect tunnel account and container token environment）
- 確認: 実行（一覧・絞り込み）、テスト4件。

## 2. `/neko askgk`のClaude応答（LLM worker）

**対象**: `lib/claude/ops/llm_worker_claude.py`、`lib/claude/ops/claude-helper.sh` — `claude_prompt="…"`をClaude Code CLIで実行し、tunnels API経由で回答を返す。

- 元の`llm_worker.py`を読み込み、Claudeの起動部分だけを差し替える。ソケット`/run/lib-codex/worker.sock`、ジョブ、bwrap＋`codex-web`への切替は元のまま。
- helperはsandbox内の`/run/claude-helper`へ読取専用でbind。CLIは`/opt/claude-web/claude`、なければnpmのネイティブバイナリ。
- 作業ディレクトリが`/root`配下なら、sandbox内の`/root`を空にして作業ディレクトリだけを見せる。
- 元: `ops/llm_worker.py`（[`6715fe0`](https://github.com/nekoserver/lib/commit/6715fe0) 2026-10-23）、`ops/claude-helper.sh`（[`e8f01d5`](https://github.com/nekoserver/lib/commit/e8f01d5) 2026-10-22 effortをlowへ）
- 確認: 署名付きPOSTで`done`・`reply`・`llm_model: claude-opus-5-5`（約6秒）、sandbox内の見え方、テスト5件。Slackからの通しは未確認。

## 3. askgkの待ち時間300秒

**対象**: `lib/claude/api/tunnels.claude.rb`の`LlmPrompt.run`の差し替え — メッセージ付きの要求で、LLMの回答を待つ上限を90秒から300秒にする。

- 投入のみ（`wait 0`、`ask_id`で照会）の呼出しは0のまま。2回読み込んでも差し替えは1回だけ。
- 元: `api/llm_prompt.rb`（[`a43268c`](https://github.com/nekoserver/lib/commit/a43268c) 2026-10-15）、`api/tunnels_lib.rb`の待ち90秒。
- 確認: テストで渡る値（300／0）を確認。実際に300秒かかる応答、本体Worker側の待ち時間（D1、既定120秒）、Apacheのタイムアウトは未対応。

## 4. 会話observer（表示）

**対象**: `lib/claude/ops/chat_observer_claude.py`の`watch` — Claude Codeのセッション記録から、元のobserverと同じ形の会話スナップショットを配信する。

- ソケット・プロトコル・出力の形は元と同じで、`chat_websocket.py`・`chat_http_stream.py`がそのまま使える。
- 思考過程、コマンドの入出力、meta、サブエージェントは出さない。状態は`turn_duration`または最終回答で`idle`。
- 監視対象は`LIB_CHAT_CLAUDE_SESSION`（IDまたは`workspace:/パス`）と、非公開の`claude-source.json`。
- 元: `ops/chat_observer.py`（[`a9c62d5`](https://github.com/nekoserver/lib/commit/a9c62d5) 2026-10-28 feat: AIチャット経由のSPEC評価依頼とEVAL保存確認を追加）
- 確認: `chat_websocket.py`経由の`observe`で受信、テスト。

## 5. 会話observer（送信）

**対象**: `lib/claude/ops/chat_observer_claude.py`の`send` — 認証済みの利用者の入力を、監視中のClaudeセッションへ送る。

- `claude -p --resume <id> -- <text>`。`--`で、`-`で始まるテキストもプロンプトとして渡す。
- 元: 同上。
- 確認: 専用セッションへ`--version …`・`-p --model x …`・`--help …`で始まるテキストを送り、返答と状態の変化（`idle → active → idle`）を確認。人が操作中のセッションへの同時書き込みは未対策（PLAN段階5）。

## 6. SPEC評価の依頼（spec-eval）

**対象**: `lib/claude/ops/chat_observer_claude.py`の`spec-eval`（`lib/ops/spec_eval.py`を使用） — SPECに対するEVALの作成依頼を受け付け、監視中の会話へ送る。

- `inspect`と、`create`の受付・送信は動く。
- **EVALの保存までは完了しない**。`claude -p --resume`のセッションに対象リポジトリの権限がないため（PLAN段階5で判断）。
- 元: `ops/spec_eval.py`（[`a9c62d5`](https://github.com/nekoserver/lib/commit/a9c62d5) 2026-10-28）
- 確認: 使い捨ての複製リポジトリで実行（2026-11-02）。

## 7. 起動設定

**対象**: `lib/claude/ops/chat-observer-claude.service`、`llm-worker-claude.service`、`start-llm-worker-claude.sh` — systemdのあるホストとないホストで、別名版を起動する。

- serviceは`/var/www/html/lib/claude`への配置が前提。observerは元と同じソケットを使うため`Conflicts=chat-observer.service`。
- `start-llm-worker-claude.sh`は、ソケットに応答があれば何もしない。ログは`/tmp/llm-worker-claude.log`。
- 確認: このホストで`start-llm-worker-claude.sh`による起動。コンテナ起動時の自動起動は未設定（cf-containerの`entrypoint.sh`）。

## 8. ストリーム接続先の導出（コンテナ側）

**対象**: `lib/claude/ops/stream_routes.py` — コンテナのCloudflare Tunnelのingress（`/etc/cloudflared/ingress.yml`）から、ストリームの接続先を導く。

- どの公開ホストがこのコンテナに届くかは、起動したトンネル（`NEKOROOT_HOSTNAME`から作るingress）で変わる。埋め込みページは自分のホストへ接続するため、ストリームのサーバーはそのOriginを`LIB_CHAT_ORIGINS`で許可する必要がある。
- ingressのうち、パス指定なしでApache（8443）へ向かうホスト名を接続先とする。テンプレートの置換前（`__NEKOROOT_HOSTNAME__`）は拒否する。
- `env`: 既存の`LIB_CHAT_ORIGINS`を残したまま、トンネルのホストを加えた値を出力。
- `worker --id ID`: 本体Workerの台帳（機能9）に入れる経路のJSON。
- `endpoints`: 埋め込み・WebSocket・SSE・NDJSON・JSON Text SequenceのURL。パスは本体Workerの`conversationStreamEndpoints`と同じで、libのクライアント（`chat/app.mjs`・`chat/http-stream.mjs`）が使うパスとの一致をテストで確認する。
- 確認: テスト6件、このホストのingressで`mygw.nekomaneki.work`を導出。

## 9. ストリーム接続先の台帳（本体Worker側）

**対象**: 本体Worker（`/root/cloudflare-workers-github-oauth-1`）の`src/utils/conversationStreamRoutes.ts`、`src/data/conversation-stream-routes.json`、およびそれを使う`conversationStreamHosts.ts`・`conversationStreamHealth.ts`・`views/conversationStreamPanel.ts`・`views/aichat.ts`・`index.ts`（`/aichat`のCSP、`/api/aichat/conversation-stream/health`）・`types.ts` — AIチャットのストリームパネルの接続先を、コード変更なしで、起動中のコンテナのトンネル公開ホストへ切り替える。

- それまで接続先は4か所に固定値で書かれていた（`conversationStreamHosts.ts`の表、パネルの`<option>`、死活確認、CSPの`frame-src`）。これを1つの台帳と解決関数にまとめた。
- 台帳: 経路ごとに`id`・`origin`（トンネルの公開ホスト）・`label`（省略時はホスト名）・`enabled`。`autoPriority`は「自動」で試す順（省略時は表示順）。
- `CONVERSATION_STREAM_ROUTES`（Workerの変数、台帳全体のJSON）で差し替える。未指定時は同梱の台帳（従来の4つ、表示順・自動の順も従来どおり）。askgkの経路台帳（`ASKGK_ROUTES`）と同じ方式。
- 明示した台帳が不正なら既定へ戻さない。死活確認は500と理由、`/aichat`は`frame-src 'none'`にしてパネルに理由を表示し、開始できなくする。
- `conversationStreamEndpoints(origin)`で、1つのoriginから埋め込みと各通信方式のURLを組み立てる。
- 元: `conversationStreamHosts.ts`・`conversationStreamPanel.ts`（[`f4273a8c`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/f4273a8c) 2026-10-26 feat: add Redmine observer as auto stream host）、`containerEndpoints.ts`（[`ae340fdf`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/ae340fdf) 2026-10-21）、`conversationStreamHealth.ts`（[`264d4c72`](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/commit/264d4c72) 2026-10-21）
- 確認: 関連テスト37件（新規の台帳テスト、死活確認、エンドポイント、CSP、パネル）。出力したページの`<script>`を`node --check`（既定・別の台帳・設定エラーの3通り）。デプロイ、本番での切替は未実施。
- 既存テスト2件（`aichat-stream-frame-csp.test.ts`、`conversation-stream-health-endpoint.test.ts`）は、変更前からRedmine追加後の順序に追従しておらず失敗していた。今回の変更で実際の順序に合わせた。

### コンテナを切り替えるときの手順

1. コンテナ側: `python3 lib/claude/ops/stream_routes.py env`の値を、ストリームのサーバー（`chat_websocket.py`・`chat_http_stream.py`）の`LIB_CHAT_ORIGINS`に設定して再起動する。
2. 同じく`stream_routes.py worker --id <ID>`の出力を、本体Workerの`CONVERSATION_STREAM_ROUTES`の`routes`に加える（必要なら`autoPriority`も）。
3. 本体Workerの変数を更新する（デプロイは利用者の環境から）。次のリクエストから反映される。

## 10. テストと手動確認の手順

**対象**: `lib/claude/test` — 別名版の差し替え部分を検証するテストと、実際にClaudeを呼ぶ確認の手順。

| ファイル | 件数 | 内容 |
|---|---|---|
| `chat_observer_claude_test.py` | 7 | 表示の非公開項目、状態、監視先の切替、送信の引数、CLIの選択 |
| `llm_worker_claude_test.py` | 5 | bwrapの引数（helperのbind、`/root`の扱い） |
| `stream_routes_test.py` | 6 | ingressの読み取り、URLの導出とlibクライアントとの一致、`LIB_CHAT_ORIGINS`、Workerの台帳 |
| `tunnels_claude_rb_test.rb` | 4 | `--json`、接続数、待ち時間、読み込みでCGIが動かないこと |
| `manual/MANUAL_CHECKS.md` | — | askgkの応答、observerの送信の確認手順（`askgk_request.rb`、`observer_send.py`） |

実行: `lib`で`python3 -m unittest discover -s claude/test -p '*_test.py'`と`ruby claude/test/tunnels_claude_rb_test.rb`。
