# lib/claude: Claude Code環境で動かす別名版

本番レイアウト（`/home/box/.rbenv`、`/opt/claude-web`、`/app/lib`、`/usr/local/libexec/lib-*`、Codex app-server）が無いホスト、特にClaude Codeが動くcf-containerで、tunnels API・会話observer・LLM workerを動かすための別名版。元ファイル（`lib/api/*`、`lib/ops/*`）は一切変更しない。別名版は元を読み込み、環境依存の箇所だけを差し替える。

## 構成

```
lib/claude/
├── api/tunnels.claude.rb             tunnels API（元: api/tunnels.rb）
├── ops/chat_observer_claude.py       会話observer（元: ops/chat_observer.py）
├── ops/chat-observer-claude.service
├── ops/llm_worker_claude.py          LLM worker（元: ops/llm_worker.py）
├── ops/claude-helper.sh              Claude CLIヘルパー（元: ops/claude-helper.sh）
├── ops/llm-worker-claude.service
├── ops/start-llm-worker-claude.sh    systemdの無いホスト用の起動
├── ops/start-chat-observer-claude.sh observerの起動（同上）
├── ops/restore-claude-host.sh        初期設定時の復元（CGI公開・worker・observer）
├── ops/apache-lib-tunnels.conf       /lib/api/tunnelsをCGIへ通すApacheの設定
├── test/chat_observer_claude_test.py
├── test/llm_worker_claude_test.py
├── test/tunnels_claude_rb_test.rb
├── test/restore_claude_host_test.py
└── test/manual/                      実際にClaudeを呼ぶ確認の手順とスクリプト（MANUAL_CHECKS.md）
```

`tunnels.claude.rb`は、CGIとして直接実行されたときだけ`run!`する（テストから読み込めるようにするため）。2回読み込んでも待ち時間の差し替えは1回だけ行う。

共通処理は元から読む。`tunnels.claude.rb`は`../../api/tunnels_lib`、Python版は`lib/ops`をimportパスに加えて`llm_worker`・`spec_eval`を読む。

## tunnels.claude.rb

APIの形、HMAC認証、IP許可、フィルタ、`message`・`ask_id`・`claude_prompt=`等の振り分けは`tunnels.rb`と同じ。差分のみ:

- shebangは`#!/usr/bin/env ruby`（PATH上のruby）。
- `cf tunnels list --json`で取得する。`--json`なしの出力は表形式でJSONとして読めない（元では`json_parse_error`）。
- `connections`が配列でなく接続数（整数）で返る場合はその値を`count`とする。`colos`・`created_at`は`cf`が返さないため空になる。
- エンジンの先頭（`codex_prompt=`等）が無い`message`はClaudeへ送る（`tunnels-claude.rb`と同じ`default_engine: :claude`）。元は参謀（`ask_sanbo.rb`）へ送り、このホストでは`/var/lib/lib-api/ask`が無く例外で落ちる（2026-11-02確認）。
- Claudeへのプロンプトの前に、その要求で取得済みのトンネル一覧（`sanitize_tunnel`後の`tunnels`、`fetched_at`、`error`）を添える。workerのsandboxにはCloudflareの認証情報が無く（`cf`は`CLOUDFLARE_ACCOUNT_IDが未設定`）、PID名前空間も別でcloudflaredが見えないため、添えないと「トンネルは動いていない」と誤答した（2026-11-02確認）。Codexへのプロンプトは変えない。
- `message`付きのLLM要求の待ち時間を90秒から300秒にする（`LlmPrompt::WAIT_SECONDS`）。`wait 0`（投入のみ、`ask_id`で照会）の呼出しは0のまま。CGIを置くWebサーバーのタイムアウトは300秒より長くすること。

## chat_observer_claude.py

Codex app-serverの代わりにClaude Codeのセッション記録`$LIB_CHAT_CLAUDE_PROJECTS/*/<session>.jsonl`（既定`/root/.claude/projects`）を読む。ソケット`/run/lib-chat-observer/observer.sock`、プロトコル（`watch`／`send`／`spec-eval`）、出力のスナップショット形は元と同じで、`chat_http_stream.py`・`chat_websocket.py`は無変更で使える。元と同じソケットを使うため、元のobserverとは同時に起動しない（serviceは`Conflicts=chat-observer.service`）。

- 監視対象: `LIB_CHAT_CLAUDE_SESSION`にセッションID、または`workspace:/絶対パス`（そのプロジェクトで最新の記録を追う）。切替は`/var/lib/lib-chat-observer/claude-source.json`（`{"sessionId":…}`か`{"followWorkspace":…}`）。所有者が実行ユーザーで、他者に権限が無い通常ファイルだけを受け付ける。
- 公開する内容: 人が入力した発言、アシスタントの本文（途中は`commentary`、最終は`phase: null`）、ツール種別と状態、AIが付けたタイトル。思考過程、コマンド・ツール入出力、`isMeta`の発言、`<`で始まるharnessタグ、サブエージェント（`isSidechain`）は出さない。
- 状態: `turn_duration`の後、または最終回答（`stop_reason: end_turn`）の後は`idle`、ターン途中は`active`。`claude -p`の記録には`turn_duration`が書かれないため、最終回答でも判定する。
- 読込: 記録のサイズ・mtimeが変わったときだけ末尾4MiBを読み直す。
- 送信（`send`）: `claude -p --resume <session> -- <text>`をそのセッションのcwdで起動し、2秒以内に失敗終了しなければ受付とする。`--`でオプションの解釈を終わらせ、`-`で始まるテキストもプロンプトとして渡す。人が操作中のセッションに送ると2つのプロセスが同じ記録に書くため、送信には専用セッションを推奨。
- 送信に使うCLI: `LIB_CHAT_CLAUDE_BIN`、`/opt/claude-web/claude`、npmパッケージのネイティブバイナリの順で、実行できる最初のものを使う（`claude-helper.sh`と同じ代替）。どれもなければPATH上の`claude`。

## llm_worker_claude.py / claude-helper.sh

元の`llm_worker.py`をimportし、`command()`だけを差し替える。ソケット`/run/lib-codex/worker.sock`、キュー、ジョブ保存、bwrap＋setprivによる`codex-web`への切替、出力上限、CLI実行の上限300秒は元と同じ。

- Claudeヘルパーは`lib/claude/ops/claude-helper.sh`（`LIB_CLAUDE_HELPER`で変更可）。sandbox内では`/tmp`・`/run`がtmpfsのため、`/run/claude-helper`へ読取専用でbindして実行する。
- ヘルパーは`/opt/claude-web/claude`を優先し、無ければnpmパッケージのネイティブバイナリ（`…/claude-code-linux-x64/claude`）を使う。`/opt/node22/bin/claude`はネイティブバイナリの無いスタブで動かない。
- 作業ディレクトリは`LIB_LLM_WORKSPACE`、既定は`lib`（`/root/lib`）。`/root`配下の場合、sandbox内の`/root`を空のtmpfsにして作業ディレクトリだけを読取専用でbindする。`codex-web`が`/root`（0700）を辿れない問題を解消し、`/root`の他のファイルをsandboxから隠す。
- 認証は元と同じく`codex-web`の`/var/lib/codex-web/.claude/.credentials.json`等。

## stream_routes.py と本体Workerの接続先台帳

コンテナに届く公開ホストは、起動したCloudflare Tunnelのingressで決まる。ストリームのサーバーは埋め込みページのOrigin（＝そのホスト）を`LIB_CHAT_ORIGINS`で許可し、本体WorkerはAIチャットのパネルからそのホストの`/lib/conversation-embed.html`を埋め込む。両者を同じingressから導く。

- `ops/stream_routes.py`: `/etc/cloudflared/ingress.yml`のうち、パス指定なしでApache（`https://127.0.0.1:8443`または`localhost:8443`）へ向かうホスト名を接続先とする。`env`（`LIB_CHAT_ORIGINS`、既存値を残す）、`worker --id`（本体Workerの台帳の経路）、`endpoints`（各URL）を出力する。
- URLのパス: 埋め込み`/lib/conversation-embed.html`、WebSocket`/lib/api/chat/ws`（`wss`）、SSE・NDJSON・JSON Text Sequence`/lib/api/chat/{sse,ndjson,jsonseq}`。本体Workerの`conversationStreamEndpoints`と同じ。
- 本体Worker: 台帳のファイル`src/data/conversation-stream-routes.json`（`routes`に`id`・`origin`・`label`・`enabled`、任意の`autoPriority`）を書き換えて接続先を切り替える。試験運用のあいだは環境変数での差し替えは設けない（2026-11-02、利用者の判断）。不正な台帳なら止める。詳細は[`FEATURES.claude.20261102.md`](FEATURES.claude.20261102.md)の機能9。

## 初期設定時の復元（restore-claude-host.sh）

コンテナの再起動で、`/var/www/html/lib`、Apacheの設定、worker・observerは消える。rootで`claude/ops/restore-claude-host.sh`を実行すると次を行う。何度実行してもよい。

1. `lib/api`と`lib/claude/api`を`/var/www/html/lib`へ複製する（`/root`は0700で`www-data`が辿れない）。
2. `/etc/apache2/lib-secrets.conf`（0600）に`ORIGIN_HMAC_SECRET`とCloudflareのトークンを書く。トークンは`LIB_TUNNELS_CF_TOKEN`、無ければ実行者の`CF_CONTAINER_API_TOKEN`。entrypoint.shがApacheに渡すトークン（`/etc/profile.d/cf-env.sh`）では`cf tunnels list`が`[]`になるため使わない（2026-11-02確認）。
3. `apache-lib-tunnels.conf`を`/etc/apache2/lib-tunnels.conf`に置き、VirtualHostの`ProxyPass /`より前でIncludeする。これが無いとApacheが全パスを`server.js`へ送り、`/lib/api/tunnels`はデモの固定JSONを返す（`/neko askgk`は「tunnelsの応答にreplyが含まれていません」）。CGIのタイムアウトは330秒。
4. Apacheを再読込し、`start-llm-worker-claude.sh`と`start-chat-observer-claude.sh`で起動する。observerの監視対象は既定で`workspace:/root`。

確認（2026-11-02）: 実行後、Apache経由の`/lib/api/tunnels`でトンネル2件、Workerと同形の署名付きPOSTで`ask_status: done`と`reply`が返る。Slackからの`/neko askgk`は未確認。

## 検証済み（2026-11-01〜02、cf-container上）

- `tunnels.claude.rb`: GET/HTML・`status=healthy`の絞込でトンネル一覧を返す。
- `/neko askgk claude_prompt="hello"`と同形の署名付きPOST（`status=healthy`、`format=json`、`wait_seconds: 0`）に、起動中の`llm_worker_claude.py`経由で`ask_status: done`、`reply`、`llm_model: claude-opus-5-5`を約6秒で返す。署名なしは`401 hmac_required`。
- sandbox内で`pwd`は`/root/lib`、`ls -A /root`は`lib`のみ、`/root/lib`のファイルを読める。
- 待ち時間: メッセージ付き要求でworkerへの待ちに300が渡ることをスタブで確認。実際に300秒かかる応答は未試験。
- observer: 本来のソケットで起動し、`chat_websocket.py`（テスト用鍵）経由の`observe`でこの会話のスナップショットとheartbeatを受信。誤った署名は`1008 authentication_failed`。
- observerの送信: 専用セッションへ`--version …`・`-p --model x …`で始まるテキストを送り、プロンプトとして扱われて返答（`PONG`・`PING2`）が届くこと、状態が`idle`→`active`→`idle`と変わることを確認（2026-11-02）。
- `spec-eval create`: 使い捨ての複製リポジトリで、受付（`pending`）と依頼の送信まで動いた。EVALは作られなかった。送信は`claude -p --resume`で、セッションの作業ディレクトリ外の対象リポジトリを読む権限がなく、非対話のため許可も出せない（2026-11-02）。Claudeは評価をせず、その旨を会話で報告した。
- テスト: `claude/test`（Python 12件、Ruby 4件）、`test/chat_observer_test.py`、`test/chat_websocket_test.py`（10件、`PYTHONPATH=ops`が必要）、`chat_socket`・`chat_reconnect`（JS）、`llm_prompt`・`tunnels_claude`・`llm_worker`。

## 未確認・未対応

- Slack → Cloudflare Worker → rust-worker-sqlx-d1 → tunnels API の経路。応答が待ち時間内に返ったため、`ask_id`照会の経路も未通過。
- `/neko askgk`はCloudflare Worker側でD1の「askgkの待ち時間」（既定120秒）で打ち切る。300秒待たせるには本番`/settings`で300に変更が必要（未変更）。
- workerは手動起動（`start-llm-worker-claude.sh`、ログ`/tmp/llm-worker-claude.log`）。コンテナ再起動で止まる。常駐にはcf-containerの`entrypoint.sh`への追加が必要（未変更）。
- このホストのApacheは`/lib/api/tunnels`だけを`restore-claude-host.sh`でCGIへ通す。他の`/lib`は公開しない。
- observerの`spec-eval create`はEVALの保存まで完了しない（上記）。送信時に対象リポジトリの読み書きを許可する必要があるが、権限を広げる判断のため未実装。Codex版observerとCodex app-serverの接続は、このホストにapp-serverが無く未試験。

## 反映

1. `lib/claude`をlibと同じ配置（例: `/var/www/html/lib/claude`）に置く。serviceの`ExecStart`はこの配置を前提とする。
2. `codex-web`のClaude認証を用意し、`start-llm-worker-claude.sh`またはservice定義でworkerを起動。元のworkerと同時に起動しない（同じソケット）。
3. observerを使う場合は`/etc/lib-chat.env`に`LIB_CHAT_CLAUDE_SESSION`を設定し、`chat-observer-claude.service`を起動。
4. CGIを公開する場合、`claude/api`でのCGI実行とタイムアウト（300秒超）を設定。
5. 必要なら本番のaskgk待ち時間を300秒に変更。
