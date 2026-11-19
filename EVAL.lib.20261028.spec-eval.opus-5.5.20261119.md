# 評価: tree-viewからのSPEC評価（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.lib.20261028.spec-eval.md`](SPEC.lib.20261028.spec-eval.md)（2026-11-19の改訂版、SHA256 `669f2bcd295de0933d4b6e6fcae55d2648947eb7fc8e15bd7f94baa1a321f022`）
評価対象: `nekoserver/lib`の`main`（`592f438`）の`ops/spec_eval.py`（最後の変更は`a9c62d5`、2026-10-28）と、本体のdemoコンテナで動くClaude版のobserver
区分: [`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

受付・保存・対応付けの仕組み（REQ-SE-2〜5）はテストで満たされ、observerのinspectも実物で動いた。EVALの作成（create）は、このコンテナのClaude版のobserverでは保存まで完了しない（SPECの改訂で「現状」に記録した）。経路と認証（REQ-SE-1）は、HTTP側をテストで確かめ、実際のブラウザからは試していない。

| 区分 | 要件 |
|---|---|
| 充足（テスト） | REQ-SE-2〜5 |
| 一部 | REQ-SE-1（ソケットのinspectは実物で動いた。ブラウザ・HTTPの経路は未確認） |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-SE-1 | 一部 | observerのソケットへ`{"op":"spec-eval","action":"inspect",...}`を送り、本体の`SPEC.cloudflare-workers-github-oauth-1.20260313.diff.md`に`available: true`・`connected: true`が返った。HTTPの`POST /lib/api/chat/spec-eval`は`ops/chat_http_stream.py`の246行に経路がある。セッションの確認・Originの再検証を実際の要求で確かめてはいない |
| REQ-SE-2 | 充足（テスト） | `test/spec_eval_test.py`（7件通過）。実物では、lib（既定の対象外）へのinspectが`evaluation_unavailable` |
| REQ-SE-3 | 充足（テスト） | `spec_eval.py`の49行（同じ接尾辞）、87〜97行（説明付き接尾辞は本文の明示的な参照があるときだけ）。今回のEVALの名前（`EVAL<接尾辞>.opus-5.5.20261119.md`）はこの規則で対応付けられる形にした |
| REQ-SE-4 | 充足（テスト） | 同上のテスト。受付の置き場所`/var/lib/lib-chat-observer/`は今は空（受付の記録が無い） |
| REQ-SE-5 | 充足（テスト） | 同上 |

---

## 提案（未実施）

1. libを対象にするか決める。対象にしないなら、libのSPECは[`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順で評価する、とtree-viewの画面か文書に出す。
2. Claude版のobserverでcreateを完了させるには、送り先のセッションに対象リポジトリの読み書きを許す必要がある（権限を広げる判断。利用者が決める）。

---

## 確かめていないこと

- ブラウザ（tree-view → 埋め込みページ）からのinspect・create。
- Codex版のobserverとCodexの固定会話での、createからEVALの保存まで。
- 「反映」の5（dynamicneko側の表示）。
