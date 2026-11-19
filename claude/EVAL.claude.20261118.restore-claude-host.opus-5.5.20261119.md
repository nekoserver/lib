# 評価: restore-claude-host.sh（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.claude.20261118.restore-claude-host.md`](SPEC.claude.20261118.restore-claude-host.md)（2026-11-19の改訂版、SHA256 `5a173ff37de7c8860b52f23a20cebce2c5ff20324007aa42eb15cfeecbeca16f`）
評価対象: libの`main`（`592f438`）の`claude/ops/restore-claude-host.sh`と、本体のdemoコンテナ（2026-11-18 22:10起動）での起動時の実行
区分: [`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

10の要件をすべて満たす。起動時のログ（entrypointの呼び出し、22:22:50）で段0〜8が1回で通り、今の稼働の状態（Apache、4つの常駐プロセス、設定ファイル）もそのとおりだった。テストは`restore_claude_host_test.py`・Apacheの設定の3つのテストが通る。

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-RCH-1 | 充足（テスト） | `restore_claude_host_test.py` |
| REQ-RCH-2 | 充足 | ログ「/var/www/html/lib is the lib checkout itself (bind mount), nothing to copy」、`findmnt`で`/dev/vdc[/root/lib]` |
| REQ-RCH-3 | 充足 | `/etc/apache2/lib-secrets.conf`は0600（root） |
| REQ-RCH-4 | 充足 | 8443の`/lib/api/tunnels`が署名付きでCGIに届く（200） |
| REQ-RCH-5 | 充足 | ログ「route access control: on」、`/etc/apache2/lib-chat-route-access.conf`あり、経路IDによる許可が働く |
| REQ-RCH-6 | 充足 | ログ「the internal lib vhost already relays the conversation stream」、8445の`/lib/api/chat/ws`が426（中継されている） |
| REQ-RCH-7 | 充足 | ログ「Syntax OK」「listening on 8443」、`apache2 -k start`のプロセス |
| REQ-RCH-8 | 充足 | ログに4つの起動。今、`llm_worker_claude.py`（root）・`chat_observer_claude.py`（root）・`chat_http_stream.py`・`chat_websocket.py`（www-data）が動いている。元のworker・observerは動いていない |
| REQ-RCH-9 | 充足 | ログ「hooks: node_modules rebuilt with npm ci」とフック5件のOK（PR #161より前のスクリプト）。PR #161の後の段8は[`EVAL.claude.20261119.restore-claude-hooks.opus-5.5.20261119.md`](EVAL.claude.20261119.restore-claude-hooks.opus-5.5.20261119.md) |
| REQ-RCH-10 | 充足（テスト） | `restore_claude_host_test.py`（Includeを重ねない） |

`claude/test`のPython 96件はすべて通過。

---

## 提案（未実施）

1. 起動時のログに時刻を入れる（今は時刻が無く、ファイルのmtimeで推定した）。

---

## 確かめていないこと

- PR #161の後のスクリプトでの、コンテナの作り直しの直後の実行（次の起動で確かめられる）。
- 手で再実行したときの`LIB_ROUTE_ACCESS_CONTROL`の渡し忘れ（SPECの4章の既知の制約）。
