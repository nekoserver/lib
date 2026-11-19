# 評価: muse-vmの再起動後に溜まった問い合わせ（案）（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.claude.20261108.muse-restart-backlog.md`](SPEC.claude.20261108.muse-restart-backlog.md)（2026-11-19の改訂版、SHA256 `6706b54f6a5fa34f1dbaf8dd870f2b1244f0739d714793994089707ea547ced2`）
評価対象: libの`main`（`592f438`）の`claude/ops/agent-tools/`と`claude/ops/llm_worker_claude.py`
区分: [`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

この SPEC は案で、利用者の承認待ちのまま。承認・実装の記録は見つからず、REQ-MRB-1〜5はどれも実装されていない。案の前提（「届かなかった」と「処理されたが応答が消えた」を区別できない）は、今も成り立つ。

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-MRB-1 | 未実装 | `inquiry.py`に、`muse_connection_failed`で順番待ちへ積み直す処理が無い |
| REQ-MRB-2 | 未実装 | `muse-queue.py`は、workerのジョブが`pending`・`running`かで忙しさを見て送るだけ。復旧の時点で滞留分を確定する処理が無い |
| REQ-MRB-3 | 未実装 | 固定ID・状態のファイルが無い |
| REQ-MRB-4 | 未実装 | 「要確認」の状態が無い |
| REQ-MRB-5 | 未実装 | 片付いたときの通知が無い |

案の外で変わったこと: libのworkerは、muse-vmに届かないとき10秒で`muse_connection_failed`を返す（2026-11-12）。滞留が溜まる前に呼び出し側へ失敗が返るので、案の「積み直し」（REQ-MRB-1）を入れるときの起点になる。

---

## 提案（未実施）

1. この案を進めるか、取り下げるかを利用者が決める（6章の表は「進める」が案のまま）。
2. 進めないなら、SPECの状態を「取り下げ」にして、次回の定期的な見直しの対象から外す。

---

## 確かめていないこと

- `~/.claude/tools/`に置いた道具が、別のホスト（本体の作業用のホストなど）で使われているか。このコンテナには置かれていない。
