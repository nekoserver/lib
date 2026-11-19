# lib/claude: Claude Code環境で動かす別名版

作成日: 2026-11-02（作成: Claude Opus 5.5、コミット`b869b22`）
改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。11-02の版（`029811f`）より後の23コミット（muse_prompt、bridge_jobs、agent-tools、チャットの経路のアクセス制御、復元の変更、hooksの復元）を反映し、要件に番号（`REQ-CL-…`）を付けた。改訂の内容は末尾の「改訂の記録」。
評価: [`EVAL.claude.20261102.opus-5.5.20261119.md`](EVAL.claude.20261102.opus-5.5.20261119.md)（この改訂版による評価）。11-02の評価は[`EVAL.claude.20261102.md`](EVAL.claude.20261102.md)（改訂前の版による）
定期的な見直し: このSPECは[`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す。

本番レイアウト（`/home/box/.rbenv`、`/opt/claude-web`、`/app/lib`、`/usr/local/libexec/lib-*`、Codex app-server）が無いホスト、特にClaude Codeが動くcf-container（本体のdemoコンテナ、`mygw.nekomaneki.work`）で、tunnels API・会話observer・LLM workerを動かすための別名版。

- **REQ-CL-1**: 元ファイル（`lib/api/*`、`lib/ops/*`）は変更しない。別名版は元を読み込み、環境に依存する箇所だけを差し替える。
  - 現状の例外（2026-11-19の改訂で記録）: muse_promptの追加（`e2bcaa1`、2026-11-06）で、元の`api/llm_prompt.rb`のエンジンの一覧とIDの形に`muse`を足した。例外として認めるか、差し替えに戻すかは未決定。

## 構成

```
lib/claude/
├── api/tunnels.claude.rb             tunnels API（元: api/tunnels.rb）
├── ops/chat_observer_claude.py       会話observer（元: ops/chat_observer.py）
├── ops/chat-observer-claude.service
├── ops/llm_worker_claude.py          LLM worker（元: ops/llm_worker.py）。muse_promptもここ
├── ops/claude-helper.sh              Claude CLIヘルパー（元: ops/claude-helper.sh）
├── ops/llm-worker-claude.service
├── ops/start-llm-worker-claude.sh    systemdの無いホスト用の起動
├── ops/start-chat-observer-claude.sh observerの起動（同上）
├── ops/start-chat-streams-claude.sh  AIチャットのストリームのサーバーの起動（同上、www-data）
├── ops/stream_routes.py              ingressからストリームの接続先を導く
├── ops/restore-claude-host.sh        コンテナ起動後の復元（下の「復元」）
├── ops/restore-claude-hooks.sh       本体リポジトリのClaude Codeのフックの復元
├── ops/apache-lib-tunnels.conf       /lib/api/tunnelsをCGIへ通す設定と、公開側の署名ヘッダーの例外
├── ops/apache-lib-chat.conf          埋め込みページとストリームをストリームのサーバーへ通す設定、経路IDの記録
├── ops/apache-lib-chat-route-access.conf  起動オプションのときだけ置く、経路IDによる許可
├── ops/apache-lib-internal-chat.conf 内部Apache（8445）の会話ストリームの中継
├── ops/bridge_jobs.py                D1のジョブを1件ずつ取り出して片付けるCLI（スキーマ: bridge_jobs_schema.sql）
├── ops/agent-tools/                  エージェントの道具（inquiry.py・muse-queue.py・japanese-guard.js）
├── test/*_test.py, *_test.rb         自動テスト（下の「テスト」）
└── test/manual/                      実際にClaudeを呼ぶ確認のスクリプト（askgk_request.rb・observer_send.py）
```

共通処理は元から読む。`tunnels.claude.rb`は`../../api/tunnels_lib`、Python版は`lib/ops`をimportパスに加えて`llm_worker`・`spec_eval`を読む。

## tunnels.claude.rb

APIの形、HMAC認証、IP許可、フィルタ、`message`・`ask_id`・`◯_prompt=`の振り分けは`tunnels.rb`と同じ。差分のみ:

- **REQ-CL-2**: CGIとして直接実行されたときだけ`run!`する（テストから読み込めるように）。2回読み込んでも、待ち時間の差し替えは1回だけ行う。shebangは`#!/usr/bin/env ruby`。
- **REQ-CL-3**: `cf tunnels list`（`--json`なし）で取得し、出力の先頭に`result_info:`の行があれば、その後のJSON配列だけを読む。`cf 1.0.0-beta.31`は`--json`を拒む（2026-11-14）。`connections`が接続数（整数）で返る場合はその値を`count`とする。`colos`・`created_at`は`cf`が返さないため空になる。
- **REQ-CL-4**: エンジンの先頭（`codex_prompt=`など）が無い`message`はClaudeへ送る。元は参謀（`ask_sanbo.rb`）へ送り、このホストでは`/var/lib/lib-api/ask`が無く例外で落ちる（2026-11-02確認）。
- **REQ-CL-5**: Claudeへのプロンプトの前に、その要求で取ったトンネル一覧（`sanitize_tunnel`後の`tunnels`、`fetched_at`、`error`）を添える。workerのsandboxにはCloudflareの認証情報もcloudflaredのプロセスも見えず、添えないと「トンネルは動いていない」と誤答した（2026-11-02確認）。Codex・Museへのプロンプトは変えない。
- **REQ-CL-6**: `message`付きのLLM要求の待ちは最大300秒（元は90秒）。`wait 0`（投入のみ、`ask_id`で照会）は0のまま。ApacheのCGIのタイムアウトは330秒（`apache-lib-tunnels.conf`）。

## llm_worker_claude.py / claude-helper.sh

元の`llm_worker.py`をimportし、`command()`・`submit()`・`execute()`を差し替える。ソケット`/run/lib-codex/worker.sock`、キュー、ジョブ保存、bwrap＋setprivによる`codex-web`への切替、出力上限、CLI実行の上限300秒は元と同じ。エンジンは`codex`・`claude`・`muse`（`nemotron`は`unsupported_engine`）。

- **REQ-CL-7**: Claudeヘルパーは`lib/claude/ops/claude-helper.sh`（`LIB_CLAUDE_HELPER`で変更可）。sandbox内では`/tmp`・`/run`がtmpfsのため、`/run/claude-helper`へ読取専用でbindして実行する。ヘルパーは`/opt/claude-web/claude`、無ければnpmパッケージのネイティブバイナリを使う（`/opt/node22/bin/claude`はスタブで動かない）。
- **REQ-CL-8**: 作業ディレクトリは`LIB_LLM_WORKSPACE`、既定は`/root/lib`。`/root`配下なら、sandbox内の`/root`を空のtmpfsにして、作業ディレクトリだけを読取専用でbindする。
- **REQ-CL-9**（muse_prompt、2026-11-06〜12）: `muse`のジョブはsandboxの外で、tailnet経由でmuse-vmのOpenAI互換API（`muse-vm:8080`、`/v1/chat/completions`）へ送る。`tailscale nc`でソケットを運ぶ（このホストのtailscaledはユーザー空間のネットワーク）。
  - 鍵は起動時の`MUSE_API_KEY`だけ。起動直後に環境から取り除き、Codex・Claudeの実行に引き継がない。無ければ`muse_not_authenticated`。
  - 送る前に`GET /v1/models`で到達を確かめ、10秒以内に応答が無ければ`muse_connection_failed`（届かないときに`tailscale nc`が127秒ソケットを保持し、askgkがHTTP 524になったため、2026-11-12）。
  - 失敗の理由: 401・403は`muse_authentication_failed`、429は`muse_usage_limit`、それ以外の失敗・空の応答・1MiB超は`muse_execution_failed`、時間切れは`llm_timeout`。
  - 応答の前後の空白と改行は取り除く。応答の`model`を`llm_model`として保存する（無い・不正なら`muse`）。`llm_effort`は出さない。
  - 宛先は`LIB_MUSE_HOST`・`LIB_MUSE_PORT`・`LIB_MUSE_MODEL`で変えられる（既定`muse-vm`・`8080`・`muse`）。

## chat_observer_claude.py

Codex app-serverの代わりに、Claude Codeのセッション記録`$LIB_CHAT_CLAUDE_PROJECTS/*/<session>.jsonl`（既定`/root/.claude/projects`）を読む。ソケット`/run/lib-chat-observer/observer.sock`、プロトコル（`watch`・`send`・`spec-eval`）、出力のスナップショットの形は元と同じで、`chat_http_stream.py`・`chat_websocket.py`は変えずに使える。元と同じソケットを使うため、元のobserverとは同時に起動しない（serviceは`Conflicts=chat-observer.service`、復元は元を止めてから起動する）。

- **REQ-CL-10**: 監視対象は`LIB_CHAT_CLAUDE_SESSION`にセッションID、または`workspace:/絶対パス`（そのプロジェクトで最新の記録を追う）。復元が起動するときの既定は`workspace:/root`。切替は`/var/lib/lib-chat-observer/claude-source.json`（所有者が実行ユーザーで、他者に権限が無い通常ファイルだけを受け付ける）。
- **REQ-CL-11**: 公開するのは、人が入力した発言、アシスタントの本文（途中は`commentary`、最終は`phase: null`）、ツールの種別と状態、AIが付けたタイトル。思考過程、コマンド・ツールの入出力、`isMeta`の発言、`<`で始まるharnessタグ、サブエージェント（`isSidechain`）は出さない。
- **REQ-CL-12**: 状態は、`turn_duration`の後、または最終回答（`stop_reason: end_turn`）の後は`idle`、ターンの途中は`active`。記録のサイズ・mtimeが変わったときだけ、末尾4MiBを読み直す。
- **REQ-CL-13**: 送信（`send`）は、`claude -p --resume <session> -- <text>`をそのセッションのcwdで起動し、2秒以内に失敗終了しなければ受付とする。人が操作中のセッションに送ると、2つのプロセスが同じ記録に書く（送信には専用セッションを推奨）。
- **REQ-CL-14**: `spec-eval`は`ops/spec_eval.py`の`inspect`・`create`を受け付ける。対象は`LIB_SPEC_EVAL_REPOSITORIES`（既定は本体など5リポジトリ、**libは含まない**）。`create`は監視中のセッションへ`claude -p --resume`で依頼を送るだけで、EVALの保存までは完了しない（下の「未確認・未対応」）。

## stream_routes.py と本体Workerの接続先

コンテナに届く公開ホストは、起動したCloudflare Tunnelのingressで決まる。ストリームのサーバーは埋め込みページのOriginを`LIB_CHAT_ORIGINS`で許可し、本体WorkerはAIチャットのパネルから、そのホストの`/lib/conversation-embed.html`を埋め込む。両者を同じingressから導く。

- **REQ-CL-15**: `ops/stream_routes.py`は`/etc/cloudflared/ingress.yml`のうち、パス指定なしでApache（`https://127.0.0.1:8443`または`localhost:8443`）へ向かうホスト名を接続先とし、`env`（`LIB_CHAT_ORIGINS`）・`worker --id`（本体Workerの経路の形）・`endpoints`（埋め込み`/lib/conversation-embed.html`、`wss`の`/lib/api/chat/ws`、`/lib/api/chat/{sse,ndjson,jsonseq}`）を出力する。
- **REQ-CL-16**: ストリームのサーバーの`LIB_CHAT_FRAME_ORIGINS`は、`LIB_CHAT_ORIGINS`に本体Workerのorigin（`https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev`、`https://dynamicneko.nekoflare.workers.dev`）を足したもの。
- 本体Worker（参考、libの要件ではない）: 接続先は台帳`src/data/conversation-stream-routes.json`（`id`・`origin`・`enabled`、任意の`label`・`autoPriority`）を既定とし、2026-11-19の本体PR #2462（`c271b7ba`）からD1の`conversation_stream_hosts`で上書きできる。11-02の「環境変数での差し替えは設けない」は今も同じ。

## 入口と制限（2026-11-11〜）

本体のdemoイメージの公開Apache（8443）は、2026-11-11から`/lib`を一律に拒否している（管理者専用）。入口の全体は[`../SPEC.lib.20261118.lib-features-access.md`](../SPEC.lib.20261118.lib-features-access.md)。別名版に関わるのは次の2つ。

- **REQ-CL-17**: 公開側の`^/lib/api/tunnels$`だけは、`X-Timestamp`と`X-Signature`の両方があれば通す（`apache-lib-tunnels.conf`、2026-11-18）。署名なしは403、不正な署名は401（CGI）。
- **REQ-CL-18**: AIチャットの経路（埋め込みページ・`/lib/chat/`・`/lib/t/`・`/lib/api/chat/*`）は、起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ`apache-lib-chat-route-access.conf`を置き、経路ID（`treeview-worker`・`aichat-panel`・`health`）のある要求だけを通す。経路IDは埋め込みページの`?via=`で受け取り、Cookie`lib_chat_via`で後の要求に引き継ぐ。記録は`/var/log/apache2/lib-chat-via.log`。オプションが無ければ、チャットの経路も403のまま。

## 復元（restore-claude-host.sh）

コンテナを起動し直すと、Apacheの設定、worker・observer・ストリームのサーバー、`~/.claude`は消える。本体のentrypointが、`/root/lib`が届くのを待って`/var/www/html/lib`へbind mountし、rootでこのスクリプトを呼ぶ（本体`containers/demo/lib-restore-wait.sh`、2026-11-18。ログ`/tmp/restore-claude-host.log`）。段ごとの内容・変更の履歴・テストは[`SPEC.claude.20261118.restore-claude-host.md`](SPEC.claude.20261118.restore-claude-host.md)、フックの段は[`SPEC.claude.20261119.restore-claude-hooks.md`](SPEC.claude.20261119.restore-claude-hooks.md)が正。

- **REQ-CL-19**: 何度実行してもよい。`/var/www/html/lib`が`/root/lib`のbind mountなら複製しない。Includeを重ねない。動いている常駐プロセスは起動し直さない。元のworker・observerが同じソケットで動いていれば止めてから起動する。
- **REQ-CL-20**: 秘密の値は`/etc/apache2/lib-secrets.conf`（0600）にだけ書く。Cloudflareのトークンは`LIB_TUNNELS_CF_TOKEN`、無ければ実行者の`CF_CONTAINER_API_TOKEN`。
- **REQ-CL-21**: Apacheは`apache2ctl`でなく`/usr/sbin/apache2 -k start|graceful`で操作し、8443の待ち受けを確かめる。
- **REQ-CL-22**: 最後に本体リポジトリのフックを復元する（どのディレクトリでも働くガードを`~/.claude/settings.json`へ書き、全体テストのガードが実際に止めることを確かめる）。失敗しても前の段は戻さない。

## bridge_jobs.py（2026-11-08〜）

本体コンテナのClaude Code・Codex CLIが、D1（`agent-inquiries`）に積まれたジョブを1件ずつ取り出して片付けるCLI。仕様の正は本体の`SPEC.cloudflare-workers-github-oauth-1.20261107.bridge-job-queue.md`の5章・12章。

- **REQ-CL-23**: 取り合いはD1の条件付きUPDATE 1文と`claim_token`で決め、時刻はD1の時計だけを使う。トークンの比較は定数時間（`hmac.compare_digest`）。変更件数は1件以上で判定する。
- **REQ-CL-24**: `run-once --executor claude|codex`は、ジョブの本文を標準入力で渡して実行し、結果を`claim_token`ごとに保存する。期限は5分ごとに延ばし、延ばせなければ子を止める。外部へ書き込むジョブ（`--external`）は1回だけ試す。子プロセスにはトークンや秘密の値を渡さない（環境は許可リストの変数だけ）。Claudeは`claude-helper.sh`と同じ順でネイティブのバイナリを探す。
- 起動は手動で1件ずつ。常駐・定期実行はしない。

## agent-tools（2026-11-08〜）

エージェント（Claude Code）が使う道具。`~/.claude/tools/`・`~/.claude/hooks/`に置いて使う前提で、復元はこれを置かない。

| ファイル | 内容 |
|---|---|
| `inquiry.py` | Muse・Codexへの問い合わせと、D1`agent-inquiries`への記録をまとめる。問い合わせの末尾に標準の答え方を付ける |
| `muse-queue.py` | Museへの質問の順番待ち（`~/.claude/tools/muse-queue`） |
| `japanese-guard.js` | 利用者に見える文章を日本語に縛るフック（Stop・PreToolUse）。本体リポジトリの`claude-japanese-guard.js`とは別物 |

- **REQ-CL-25**: agent-toolsの状態ファイル（`state/`）はリポジトリに入れない（`.gitignore`）。

## テスト

- **REQ-CL-26**: `cd claude/test && python3 -m unittest discover -p '*_test.py'`（Python）、`ruby claude/test/tunnels_claude_rb_test.rb`（Ruby）、`node --test claude/ops/agent-tools/japanese-guard.test.js`（Node）がすべて通ること。Apacheの設定のテストは使い捨てのApacheを起動して確かめる。

## 未確認・未対応

- observerの`spec-eval create`は、EVALの保存まで完了しない。送信は`claude -p --resume`で、セッションの作業ディレクトリの外の対象リポジトリを読み書きする許可が無く、非対話のため許可も出せない（2026-11-02）。権限を広げる判断のため未実装。libは対象リポジトリの既定に入っていない。
- Slack → Cloudflare Worker → rust-worker-sqlx-d1 → tunnels API の経路を、このSPECの改訂の作業の中では通していない。askgkはWorker側でD1の「askgkの待ち時間」（既定120秒）で打ち切る。
- bridge_jobs.pyを本番のD1で動かした結果。
- agent-toolsを`~/.claude`に置く手順（復元の対象外）。
- Codex版observerとCodex app-serverの接続（このホストにapp-serverは無い）。

## 経緯: 2026-11-01〜02の検証（改訂前の版の記録）

- `tunnels.claude.rb`がGET/HTML・`status=healthy`の絞込でトンネル一覧を返し、`/neko askgk claude_prompt="hello"`と同形の署名付きPOSTに、workerの経由で`ask_status: done`、`reply`、`llm_model: claude-opus-5-5`を約6秒で返した。署名なしは`401 hmac_required`（当時は公開側の拒否が無かった）。
- sandbox内で`pwd`は`/root/lib`、`ls -A /root`は`lib`のみだった。
- observerは本来のソケットで起動し、`chat_websocket.py`の経由の`observe`で会話のスナップショットとheartbeatを受信した。誤った署名は`1008 authentication_failed`。専用セッションへの送信で、`-`で始まるテキストもプロンプトとして扱われた。
- `spec-eval create`は、受付（`pending`）と依頼の送信まで動き、EVALは作られなかった。

## 改訂の記録（2026-11-19、opus-5.5）

| 箇所 | 11-02の版 | 改訂後 | 根拠 |
|---|---|---|---|
| 構成 | 15ファイル | `stream_routes.py`・`restore-claude-hooks.sh`・Apacheの設定2つ・`bridge_jobs.py`・agent-toolsを追加 | `git ls-files claude/` |
| tunnelsの取得 | `cf tunnels list --json` | `--json`なし、`result_info:`の行を読み飛ばす | `6b33eb7`（2026-11-14） |
| worker | Claude・Codexだけ | muse_promptの節を追加 | `e2bcaa1`・`4d10939`・`9288783`・`e35b8ef` |
| 入口と制限 | 記載なし（公開側から届く前提） | 公開側の拒否、tunnels APIの例外、経路IDによる許可の節を追加 | `e563864`・`ed95baf`・`d3b3abe`・`747fa96` |
| 復元 | 5段の手順をこのSPECに直接記載。「workerは手動起動」「常駐にはentrypointへの追加が必要」 | entrypointが起動時に呼ぶ。段の詳細は復元のSPECへ移し、要件だけを残した | `f18eb46`・`486d6ac`・`ba65005`・`b583c2a`・`2add69a`、本体`2fc8110c` |
| 本体の台帳 | `label`は必須、環境変数での差し替えなし | `label`は任意。D1の上書き（本体PR #2462） | 本体`origin/main`の`src/data/conversation-stream-routes.json`・`c271b7ba` |
| bridge_jobs・agent-tools | 記載なし | 節を追加 | `575d8cd`・`89a7dc0`・`3ce00ce`・`de39711`・`15378ae`・`838fd13` |
| 「反映」の節 | 本番レイアウトへの手順5つ | 削除（本番レイアウトのホストへの反映は行われておらず、このホストでは復元が担う） | — |
| 「検証済み」 | 本文 | 「経緯」へ移した | — |
