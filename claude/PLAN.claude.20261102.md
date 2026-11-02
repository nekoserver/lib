# 計画: lib/claudeの今後の拡張

作成日: 2026-11-02
状態: 計画。着手は各段階の「決めること」に合意してから。

## 前提

**対象**: `lib/claude`の別名版（tunnels API、LLM worker、会話observer）と、それを使う`/neko askgk`・チャット — [`SPEC.claude.20261102.md`](SPEC.claude.20261102.md)の現状、[`EVAL.claude.20261102.md`](EVAL.claude.20261102.md)の評価、[`SUGGEST.claude.20261102.md`](SUGGEST.claude.20261102.md)の提案を、実施の順に並べる。

進め方の原則:

- 元ファイル（`lib/api`、`lib/ops`）は変えず、`lib/claude`の別名版で行う。
- 先に失敗するテストを書き、それが通ることで完了とする。手動の確認だけで完了にしない。
- 新しい設定項目、リクエストのフィールド、本番の設定の変更は、先に合意を取る。
- 報告では、確かめたことと確かめていないことを分けて書く。

## 段階の一覧

| 段階 | 目的 | 主な作業 | 合意が必要なこと |
|---|---|---|---|
| 0 | 現状を固める | コミット・PR、テストの不足を埋める | PRの作成 |
| 1 | 常に動く状態にする | workerとobserverの常駐、タイムアウトの整合 | entrypoint・本番設定の変更 |
| 2 | 安全側の対策 | 費用上限、Bashの絞り込み | 金額、許可するコマンド |
| 3 | 体験の改善 | 逐次配信、代替モデル | 代替モデル |
| 4 | 機能の追加 | 会話の継続、構造化出力、MCPツール | APIの形、保存期間、スキーマ |
| 5 | observerの作り替え | フックでの通知、送信の安全化、SPEC評価 | 監視対象の設定変更、spec-evalの方式 |

段階0〜2は順に行う。段階3〜5は、段階2の後なら独立して進められる。

## 段階0: 現状を固める

**対象**: `lib/claude`の未コミットのファイル一式とテスト — 今の動作を、テストとコミットで再現できる状態にする。

進捗（2026-11-02）: コミットとPR以外は実施済み。詳細はEVALの「追記: PLANの段階0の実施」。`spec-eval create`は、受付と送信までは動き、EVALの保存は権限の不足で完了しない（段階5の「決めること」に追加）。

| 作業 | 完了の条件 |
|---|---|
| `tunnels.claude.rb`のテスト（`--json`の引数、接続数が整数、待ち時間の差し替え） | `ruby claude/test/…`で通る。差し替えを外すと失敗する |
| `llm_worker_claude.py`のテスト（bwrapの引数: `/root`のtmpfs、helperのbind、作業ディレクトリが`/root`外のとき何も足さない） | 通る。実際にbwrapを起動しない単体テスト |
| 手動確認に使った一時スクリプト（askgkの署名付き送信、observerの送信）を、テストか手順書として残す | 手順書に従えば、同じ確認を誰でも再現できる |
| `spec-eval create`の確認 | 専用のセッションと対象リポジトリで受付から保存まで確かめる。できなければ未確認として記録 |
| コミットとPR（`lib`のCLAUDE.mdの手順。ベースは`main`） | PRが作られ、本文に確認済み・未確認を書く |

## 段階1: 常に動く状態にする

**対象**: workerとobserverの起動、`/neko askgk`の待ち時間に関わるタイムアウト — 手動起動に頼らず、300秒の待ちが途中で切れないようにする。

| 作業 | 完了の条件 | 担当・反映先 |
|---|---|---|
| コンテナ起動時にworkerを起動（`start-llm-worker-claude.sh`） | 再起動後に`/neko askgk claude_prompt="hello"`が応答する | cf-containerの`entrypoint.sh` |
| ストリームの接続先の切替（2026-11-02に仕組みを実装、未コミット・未デプロイ） | コンテナ起動時に`stream_routes.py env`で`LIB_CHAT_ORIGINS`を設定し、本体Workerの`CONVERSATION_STREAM_ROUTES`に`stream_routes.py worker`の経路を入れて、AIチャットのパネルからそのコンテナの会話が見える | cf-containerの`entrypoint.sh`、本体Workerの変数とデプロイ |
| observerを使う場合は同様に起動し、監視対象を設定 | 再起動後に`observe`で会話が届く | 同上、`LIB_CHAT_CLAUDE_SESSION` |
| CGIのタイムアウトを300秒より長くする | 300秒かかる応答が切れずに返る（下記の試験） | Apacheの設定 |
| `/neko askgk`のWorker側の待ち時間を300秒にする | `/settings`の「askgkの待ち時間」が300 | 本番の`/settings`（管理者） |
| 300秒の通しの試験 | Slack→Worker→rust-worker-sqlx-d1→tunnels APIで、長い処理が`ask_id`照会を経て返る | 本番 |

決めること: entrypointへの追加と本番の設定変更をしてよいか。observerを常駐させるか。

## 段階2: 安全側の対策

**対象**: `claude-helper.sh` — 待ち時間を300秒にしたことで長く・高くなり得る1回の処理に、上限と制限を設ける（SUGGEST 2・3）。

| 作業 | 完了の条件 |
|---|---|
| `--max-budget-usd`を付ける | 上限に達したときの出力を実際に確かめ、workerの失敗の分類（`failure_code`）に反映。テストで分類を固定 |
| `--allowedTools`のBashをコマンド単位にする（例: `Bash(cf tunnels *)`） | askgkで使う質問（`tunnels-list`、`models-list`、`settings`、自由記述）が答えられ、許可外のコマンドが拒否されることを確かめる |

決めること: 1回あたりの金額。許可するコマンドの一覧（先に、今の質問で使われているコマンドを洗い出す）。

## 段階3: 体験の改善

**対象**: workerの実行とチャットの配信 — 待っている間に内容が見え、混雑で失敗しないようにする（SUGGEST 1・9）。

| 作業 | 完了の条件 |
|---|---|
| 逐次配信: helperに`--include-partial-messages`、workerがジョブ記録に途中の本文を書き、照会で返す。`chat_websocket.py`のキュー経路が`delta`で配信 | 長い回答で、最終回答より前に`delta`が届く。askgk（最終回答のみ）の結果は変わらない |
| 代替モデル: `--fallback-model` | 応答の`llm_model`で代替されたかが分かる |

注意: 逐次配信は`chat_websocket.py`（元ファイル）の変更が要る。別名版を作るか、元を変えるかを決める。

決めること: 代替モデル。`chat_websocket.py`の扱い。

## 段階4: 機能の追加

**対象**: tunnels APIとworker — askgkでできることを増やす（SUGGEST 6・7・8）。

| 作業 | 完了の条件 |
|---|---|
| 会話の継続: ジョブのUUIDを`--session-id`に渡し、続きの質問は`--resume`で再開 | 前の回答を前提にした質問に答えられる。会話の記録が保存期間後に消える |
| 構造化出力: 用途ごとに`--json-schema` | 例: トンネル診断が決まった形のJSONで返り、スキーマに合わないときの扱いがテストで決まっている |
| MCPツール: `sanitize_tunnel`と同じ項目だけを返すstdioのMCPサーバーを`--mcp-config`で渡す | Claudeの回答に、許可していない項目（トークン、接続元のIPなど）が出ない |

決めること: リクエストの新しいフィールド（tunnels APIとCloudflare Workerの両方の変更）、会話の保存期間、スキーマ。MCPを入れた後にBashを外すか。

## 段階5: observerの作り替え

**対象**: `chat_observer_claude.py`と`spec_eval.py`の使い方 — ファイルを1秒ごとに確認する方式と、監視中の会話へ送る方式を見直す（SUGGEST 4・5・10・11）。

| 作業 | 完了の条件 |
|---|---|
| 送信の安全化: `--bg --resume`か`--fork-session` | 人が操作中のセッションへ送っても、同じ記録へ同時に書かない。表示する会話の切り替えが決まっている |
| フックでの通知: 監視対象のセッションのフック（`UserPromptSubmit`、`PostToolUse`、`Stop`など）からobserverへ通知 | 表示の遅れがなくなり、状態は`Stop`で確定する。フックがない場合は今の方式で動く |
| SPEC評価: `--agents`で評価専用のエージェントを定義し、headlessで実行 | 監視中の会話を使わずにEVALが作られ、受付・保存の確認は今の仕様と同じ |
| 常駐コンソール（`--input-format stream-json`） | 上の2つで足りなければ検討する |

決めること: 監視対象のセッションの設定（`settings.json`）を変えてよいか。SPEC評価の方式を変えるか（今の仕様は「既存の会話を使う」）。今の方式のままにする場合、送信時に対象リポジトリの読み書きを許可してよいか（`--add-dir`と書き込みを含む`--allowedTools`。2026-11-02の確認では、許可がないためEVALが保存されなかった）。

## 行わないこと

- `--bare`への切り替え（SUGGEST 12）。`--bare`はOAuthの認証を読まないため、今の`codex-web`の認証では使えない。APIキーに切り替える場合だけ見直す。
- 元ファイルの直接の変更。必要になった場合は、その都度合意を取る。

## 確認したこと・していないこと

この計画は、SPEC・EVAL・SUGGESTの記述と、2026-11-01〜02にこのホストで確かめた結果に基づく。各段階の作業の所要時間、CLIの各オプションの実際の挙動（`--max-budget-usd`、`--json-schema`、`--bg --resume`、フック）、本番の`/opt/claude-web/claude`の版は確かめていない。
