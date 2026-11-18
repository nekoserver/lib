# agent-tools: Claude CodeがMuse・Codexと協議して記録するための道具

作成日: 2026-11-08
**対象**: 本体コンテナ（cf-container）のClaude Codeが、Muse・CodexへD1`agent-inquiries`の議題について問い合わせ、結果を記録し、作業の決まりをフックで守るための道具 — それまで毎回その場で書いていた手順を、版管理できる形にまとめた（利用者の指摘「業務の最適化とか考えないの？」）。

| ファイル | 役割 | 呼ばれ方 |
|---|---|---|
| `inquiry.py` | `ask`: Muse・Codex・Claudeへ`claude/test/manual/askgk_request.rb`で送り、結果（失敗も）を`inquiry_entries`に書く。Museは`/health`が戻るまで待つ。すべての質問に標準の答え方（問題・原因と因果・根拠・目的・効果・測り方・手順・所要時間・費用と危険、各1〜2文、800字以内）を付ける。`note`: 利用者の発言や実装の記録。`clarify`: 利用者が分からない区分（目的・因果・効果・根拠・手順・所要時間・費用・危険・代替）を指定すると、提案と議題の記録から質問を組み立て、Muse（キュー）とCodexへ送る。根拠（実物の確認）はMuseだけに頼む。`sql`: 読み取り | `~/.claude/tools/inquiry.py`（このファイルへのリンク） |
| `muse-queue.py` | Museへの質問の順番待ち。`~/.claude/tools/muse-queue/pending/*.json`（`case`・`clue`・`prompt`）を名前順に1件ずつ送る。Museの処理中のジョブが無いときだけ送る | `~/.claude/tools/muse-queue.py`。Monitorで起動し、1件ごとに通知 |
| `japanese-guard.js` | 利用者に見える文章を日本語に縛るフック。Stopでは最終の返答（`last_assistant_message`を優先）だけを見る。PreToolUseではBashの説明欄だけを見る。同じターンで止めるのは2回まで | `~/.claude/settings.json`のStop・PreToolUse(Bash) |
| `japanese-guard.test.js` | 上の確認。`node japanese-guard.test.js` | 手動 |

## 前提

- 環境変数`CLOUDFLARE_ACCOUNT_ID`と`CF_CONTAINER_API_TOKEN`（D1の読み書き）。`~/lib`で`restore-claude-host.sh`済み（workerが動いている）。
- 質問の本文に半角の二重引用符を入れない（`◯_prompt="…"`の区切りが壊れる）。
- 1つのジョブの上限は300秒。重い調べものは小分けにする（2026-11-08、4つの調べものを1件にまとめたら上限に掛かった）。

## 注意

- `~/.claude/tools`と`~/.claude/hooks`はこのディレクトリへのリンク。直すときはこちらを直す。
- フックの状態（止めた回数）は`~/.claude/hooks/state`に置く（リポジトリに入れない）。
- フックの初版は、PreToolUseで直前の文章を見たために全ツールが止まり続け、Stopでターン全体を見たために終われなくなった。判定の範囲を変えるときは、この2つの詰まり方をテストで確かめる。
