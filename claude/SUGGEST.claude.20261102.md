# 提案: lib/claudeをClaude Code独自の機能で置き換える・拡張する

作成日: 2026-11-02
状態: 提案のみ。実装・設定変更・デプロイは未実施。

## 対象と前提

**対象**: `lib/claude`の別名版（`api/tunnels.claude.rb`、`ops/chat_observer_claude.py`、`ops/llm_worker_claude.py`、`ops/claude-helper.sh`）と、これらを使う`/neko askgk`・会話observer・チャット（`chat_websocket.py`・`chat_http_stream.py`）。

現在の別名版は、Codex向けの設計をClaude Codeで「動かす」ための最小の差し替えで、Claude Code固有の機能はほとんど使っていない。以下は、使えば置き換えや追加ができるもの。

- オプションは、このホストのClaude Code 2.1.316の`claude --help`で存在を確認した。オプションの挙動は、未確認と書いたもの以外もヘルプの記述に基づく。本番の`/opt/claude-web/claude`の版は未確認。
- 新しい設定項目やリクエストのフィールドを増やす提案は、採用前に合意を取る。

## 優先度の目安

| 優先 | 提案 | 置換／追加 | 対象 |
|---|---|---|---|
| 高 | 1. 応答の逐次配信 | 追加 | worker・WebSocket |
| 高 | 2. 1回あたりの費用上限 | 追加 | helper |
| 高 | 3. Bashの許可をコマンド単位に絞る | 置換 | helper |
| 高 | 4. observerの送信を安全にする | 置換 | observer |
| 中 | 5. フックによるobserverのイベント駆動化 | 置換 | observer |
| 中 | 6. askgkの続きの質問（会話の継続） | 追加 | worker・tunnels API |
| 中 | 7. 構造化出力 | 追加 | worker・tunnels API |
| 中 | 8. tunnels情報をMCPツールとして渡す | 置換 | helper |
| 中 | 9. 混雑時の代替モデル | 追加 | helper |
| 低 | 10. 常駐プロセスによる対話コンソール | 置換 | observer |
| 低 | 11. SPEC評価をサブエージェントで実行 | 置換 | spec-eval |
| 低 | 12. 起動設定の明示化（`--bare`） | 置換 | helper |

## 1. 応答の逐次配信

**対象**: `llm_worker.py`の`run_bounded`／`execute`、`chat_websocket.py`の`event_stream`（キュー経路） — 回答を最後にまとめてではなく、生成中に少しずつ届ける。

- 現状: helperは`--output-format stream-json`で出力しているが、workerは終了後に`result`だけを取り出す。WebSocketのキュー経路は`delivery: final_answer`で、最終回答まで何も表示されない。
- 提案: helperに`--include-partial-messages`を付けると、生成途中のテキストが届く。workerはジョブ記録に途中の本文を書き、照会（`poll`）の応答に含める。`event_stream`は、デモ経路にすでにある`delta`イベントで配信する。
- 効果: 長い回答や300秒近い処理でも、待っている間に内容が見える。
- 注意: ジョブ記録の書き込み回数が増える。間引き（例: 0.5秒ごと）が必要。askgk（Slack）は最終回答だけを使うため、影響しない。

## 2. 1回あたりの費用上限

**対象**: `claude-helper.sh` — 1回の`claude_prompt`で使う費用の上限を決める。

- 現状: 上限は実行時間（300秒）と出力サイズだけ。待ち時間を300秒にしたことで、1回の処理が長く・高くなり得る。
- 提案: `--max-budget-usd <金額>`を付ける。上限に達したときの`result`の形は未確認なので、`failure_code`での分類をテストで確かめてから入れる。
- 注意: 金額はユーザーが決める。API料金ではなくサブスクリプションの認証で使う場合の効き方は未確認。

## 3. Bashの許可をコマンド単位に絞る

**対象**: `claude-helper.sh`の`--allowedTools 'Read,Grep,Glob,Bash,WebSearch,WebFetch'` — sandboxの読取専用に加えて、Claude側でも実行できるコマンドを限る。

- 現状: Bashは全コマンドを許可している。書き込みはbwrapで防げるが、外部への通信や`cf`の任意のサブコマンドは実行できる。
- 提案: `--allowedTools`はパターンを受け付ける（ヘルプの例: `"Bash(git *)"`）。`Bash(cf tunnels *)`、`Bash(cf workers list *)`など、askgkで使うものだけを許可する。`--permission-mode dontAsk`のままなら、許可外は自動で拒否される。`--disallowedTools`で`Bash(curl *)`などを明示的に拒否することもできる。
- 注意: 「設定状況」など自由記述の質問で、どのコマンドが必要かを先に洗い出す必要がある。絞りすぎると、回答が「実行できませんでした」になる。

## 4. observerの送信を安全にする

**対象**: `chat_observer_claude.py`の`send_to_console` — 人が操作中のセッションへ送ると、2つのプロセスが同じ記録に書く問題を避ける。

- 現状: `claude -p --resume <id> <text>`をそのまま起動している（SPECの注意事項）。
- 提案（どちらか）:
  - `--bg --resume <id>`: ヘルプによれば「すでに実行中のセッションなら、コピーを作ってその旨を表示する」。同時書き込みを避けられる。進行は`claude logs`／`claude attach`で追える。
  - `--resume <id> --fork-session`: 常に新しいセッションIDで続ける。元の会話は変わらない。observerの監視先を新しいIDに切り替える処理が必要。
- 注意: コピーやforkを作ると、observerが見ている会話と送った先が別になる。どちらを表示するかを決める必要がある。

## 5. フックによるobserverのイベント駆動化

**対象**: `chat_observer_claude.py`の`snapshots` — 1秒ごとに記録ファイルを調べる方式を、Claude Codeのフックからの通知に置き換える。

- 現状: ファイルのサイズとmtimeを1秒ごとに見て、変わったら末尾4MiBを読み直す。状態（作業中／待機中）は記録の`turn_duration`から推測している。
- 提案: 監視対象のセッション側で、Claude Codeのフック（`UserPromptSubmit`、`PostToolUse`、`Stop`など）を設定し、イベントをobserverのソケットに送る。observerは通知を受けたときだけ読み直す。状態は`Stop`で確定する。
- 効果: 遅延が最大1秒から即時になり、待機中の読み直しがなくなる。状態の判定が推測でなくなる。
- 注意: 監視対象のセッションの設定（`settings.json`）を変える必要がある。フックがない環境でも動くよう、今の方式を予備として残す。フックの入出力の形は、採用時に公式の文書で確かめる。

## 6. askgkの続きの質問（会話の継続）

**対象**: `claude-helper.sh`の`--no-session-persistence`、`LlmPrompt`の`ask_id` — 前の回答を前提にした続きの質問をできるようにする。

- 現状: 毎回新しい会話で、前の質問を覚えていない。
- 提案: workerがジョブのUUIDを`--session-id <uuid>`に渡して会話を保存する。続きの質問は、前の`ask_id`を添えて送り、`--resume <uuid>`で再開する。`--fork-session`を付けると、同じ回答から何通りにも続けられる。
- 注意: リクエストに新しいフィールドが要るため、tunnels APIとCloudflare Workerの両方の変更と合意が必要。会話の記録が`codex-web`のHOMEに残るので、保存期間（今のジョブ記録はTTL 1日）と削除を決める必要がある。

## 7. 構造化出力

**対象**: `llm_worker.py`の`execute`、tunnels APIの応答 — 回答を決まった形のJSONで受け取る。

- 現状: 回答は自由な文章（`reply`）だけ。
- 提案: `--json-schema <スキーマ>`で、例えばトンネル診断を`{"summary", "down_tunnels": [...], "actions": [...]}`の形で返させる。Slack表示やダッシュボードが、文章を解析せずに使える。
- 注意: 用途ごとにスキーマを決める必要がある。スキーマに合わなかったときの挙動は未確認。

## 8. tunnels情報をMCPツールとして渡す

**対象**: `claude-helper.sh`の`--mcp-config '{"mcpServers":{}}'` — Claudeが`cf`をBashで呼ぶ代わりに、型の決まったツールでトンネル情報を取る。

- 現状: MCPは空で、トンネル情報はClaudeがBashで`cf`を実行して取る。
- 提案: `TunnelsLib.fetch`・`sanitize_tunnel`と同じ許可済みの項目だけを返す小さなMCPサーバー（stdio）を作り、`--mcp-config`で渡す。提案3と合わせれば、Bash自体を外せる可能性がある。
- 効果: 秘密情報を出さない加工（`sanitize_tunnel`）が、Claudeの回答にも必ず適用される。

## 9. 混雑時の代替モデル

**対象**: `claude-helper.sh` — モデルが混雑・利用不可のときに失敗しないようにする。

- 提案: `--fallback-model <モデル>`（カンマ区切りで複数可）。使ったモデルはすでに`llm_model`として応答に出るので、代替されたかが分かる。
- 注意: 代替先のモデルはユーザーが決める。

## 10. 常駐プロセスによる対話コンソール

**対象**: `chat_observer_claude.py`の`send`／`watch` — Codex app-serverの`turn/start`に近い、送信と受信が一体の仕組みにする。

- 提案: `claude -p --input-format stream-json --output-format stream-json --replay-user-messages`を常駐させ、送信は標準入力へ、表示は標準出力の流れから作る。記録ファイルを読む必要がなくなる。
- 注意: プロセスの寿命の管理（再起動、セッションの引き継ぎ）が必要。人がターミナルで使うセッションとは別になる。提案4・5で足りるなら不要。

## 11. SPEC評価をサブエージェントで実行

**対象**: `spec_eval.py`の`create`（`send_to_console`で監視中の会話にプロンプトを流す方式） — 監視中の会話を使わずに評価を作る。

- 提案: `claude -p --agents '{"spec-evaluator": {...}}' --agent spec-evaluator`で評価専用のエージェントを定義し、headlessで実行する。`--json-schema`で、評価・根拠・未確認事項を決まった形で受け取る。
- 効果: 監視中の会話が使えない・別の作業中でも評価を作れる。人が見ている会話に評価依頼が割り込まない。
- 注意: 今の仕様（SPEC.lib.20261028.spec-eval.md）の「既存の会話を使う」という前提を変えることになる。

## 12. 起動設定の明示化（`--bare`）

**対象**: `claude-helper.sh` — 読み込む設定を明示し、ホストの設定の影響を受けないようにする。

- 現状: `--settings '{"disableAllHooks":true}' --setting-sources user --strict-mcp-config`で個別に止めている。
- 提案: `--bare`は、フック、プラグイン、CLAUDE.mdの自動探索、自動メモリなどをまとめて止め、渡したものだけで動く。
- 注意: `--bare`ではOAuthの認証情報を読まず、`ANTHROPIC_API_KEY`（または`--settings`の`apiKeyHelper`）だけになる。今の`codex-web`は`.credentials.json`（OAuth）なので、このままでは使えない。APIキーに切り替える場合だけの選択肢。

## 確認したこと・していないこと

- 確認: 上記のオプションが、このホストのClaude Code 2.1.316の`--help`に存在すること。
- 未確認: 各オプションの実際の挙動（特に`--max-budget-usd`の上限到達時、`--json-schema`の不一致時、`--bg --resume`のコピー作成、フックの入出力の形）。本番の`/opt/claude-web/claude`の版。
