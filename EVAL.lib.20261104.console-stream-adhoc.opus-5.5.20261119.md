# 評価: mygwストリームへの投稿（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.lib.20261104.console-stream-adhoc.md`](SPEC.lib.20261104.console-stream-adhoc.md)（2026-11-19の改訂版、SHA256 `5056f012f2f7e2b4a9ac3b54268e7bce204436c950b58f0aec2bbb9e3c976219`）
評価対象: `nekoserver/lib`の`main`（`592f438`）の`ops/chat_observer.py`・`ops/chat_http_stream.py`・`claude/ops/chat_observer_claude.py`と、本体のdemoコンテナ（mygw）で動くobserver
区分: [`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

SPECが書かれたときのmygwのobserverはCodex版だったが、今はClaude版に替わっている。Codex版のコードは11-05の一本化の方針（同じ会話へ、`thread/queue/add`で）のまま残っている。Claude版は同じ会話へ送るが、`thread/queue/add`に当たる仕組みが無く、人が操作中のセッションへ送ると2つのプロセスが同じ記録に書く。投稿は今回は実際に試していない（人が操作中のセッションに書き込むため）。

| 区分 | 要件 |
|---|---|
| 充足（コード・テスト） | REQ-CS-1・3・4・5 |
| 該当なし（mygwでは） | REQ-CS-2（Codex版だけの要件。mygwはClaude版） |
| 未確認 | REQ-CS-6（画面の表示） |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-CS-1 | 充足（コード） | Codex版: 固定した会話IDへ`thread/resume`→`thread/queue/add`（`ops/chat_observer.py`の113〜121行）。Claude版: 監視中のセッションIDへ`claude -p --resume`、送る前に監視対象が変わっていないかを確かめる（`console_target_changed`、`chat_observer_claude.py`の247〜250行） |
| REQ-CS-2 | 該当なし | Codex版のコードはある（`already has an active writer`→`console_in_use`→`thread/queue/add`）。mygwではClaude版が動いており、この経路は通らない |
| REQ-CS-3 | 充足（コード） | `ops/chat_http_stream.py`の155〜156行で`console_in_use`を409にする |
| REQ-CS-4 | 充足（実物・コード） | observerへの`watch`はスナップショットを返すだけで、Claudeのプロセスは起動しなかった（`watch`の前後でobserverの子プロセスが増えていない）。Claude版の`claude -p`は`send`のときだけ |
| REQ-CS-5 | 充足（テスト） | `test/chat_session_test.py`・`test/chat_console_input_test.py`などが通過（2026-11-19、`test/`の183件中182件が通過。落ちた1件はMuseのgit表示のテストで、この要件と関係ない） |
| REQ-CS-6 | 未確認 | 画面（`chat/app.mjs`）は今回は見ていない |

---

## 提案（未実施）

1. Claude版のobserverの投稿先を、人が操作しない専用のセッションに固定する（SPECのREQ-CL-13の推奨）。今は`workspace:/root`で、人が`/root`で始めたセッションへ書き込む。
2. 恒久設計の6項目は未着手のまま。Claude版に替わったことで、「1つの実行サーバーが書き込みを管理する」の前提（Codex app-server）が変わった。恒久設計をClaude Code前提で書き直すかを決める。

---

## 確かめていないこと

- 実際の投稿（公開のconsole API → observer → 応答）。
- ブラウザの画面での表示。
- コンテナの作り直しの後の、会話の選択の復元。
