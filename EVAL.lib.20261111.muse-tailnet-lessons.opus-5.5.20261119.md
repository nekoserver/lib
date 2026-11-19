# 評価: Museへの経路（tailnet）で決めておくこと（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.lib.20261111.muse-tailnet-lessons.md`](SPEC.lib.20261111.muse-tailnet-lessons.md)（2026-11-19の改訂版、SHA256 `df5dc213365e12b779ac73c08147068c95ec4f7e8fa9cb1643939ef3adcce403`）
評価対象: libの`main`（`592f438`）のmuse_prompt（`claude/ops/llm_worker_claude.py`）、本体の`origin/main`（`c271b7ba`）、muse-monitorの`main`（`6eafcab`、GitHub APIで読んだ範囲）、本体のdemoコンテナのtailnet
区分: [`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

この SPEC は3つのリポジトリにまたがる。libで確かめられるのはmuse_promptの経路だけで、本体・muse-monitorは、ファイルとコミットの一覧を読んだ範囲。

---

## 総合

| 要件 | 判定 |
|---|---|
| REQ-MT-1（出口を1つに） | 未充足（利用者の判断待ち） |
| REQ-MT-2（契約テスト） | 未確認 |
| REQ-MT-3（鍵の表） | 一部 |
| REQ-MT-4（失敗の理由） | 充足（libの範囲） |
| REQ-MT-5（実経路の確認） | 充足（libの範囲） |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-MT-1 | 未充足 | `tailscale status`（コンテナの中）に、本体のDOのノード`main-worker-muse`（15分前からoffline）、`muse`、このコンテナの`cf-demo-container`、`muse-vm`がある。muse-monitorのDO（`src/do.ts`）も別のノードを持つ。libのmuse_promptはこのコンテナのtailscaledから送る。SPECのとおり、寄せるかは利用者の判断待ち |
| REQ-MT-2 | 未確認 | 本体の`@ai-ecoverse/wasm-tailscale`は`1.104.1-13`のまま。muse-monitorの契約テストの中身は今回は読んでいない |
| REQ-MT-3 | 一部 | libのworkerは`MUSE_API_KEY`だけを使い、起動直後に環境から取り除く。鍵の出どころを状態として見せる口は、libのworkerには無い（無いときの`muse_not_authenticated`だけ） |
| REQ-MT-4 | 充足（libの範囲） | `muse_connection_failed`・`muse_authentication_failed`・`muse_usage_limit`・`muse_execution_failed`・`muse_not_authenticated`・`llm_timeout`（`llm_worker_claude.py`、`llm_worker_muse_test.py`が通過）。送り直してよいかの区別は、到達の確認（`GET /v1/models`）で失敗したら「まだ届いていない」と分かる形 |
| REQ-MT-5 | 充足（libの範囲） | 公開側のApache → tunnels API → worker → `tailscale nc` → muse-vm:8080 を1回通した。`muse_prompt="PONG とだけ答えて"`が200、21.6秒、`reply: "PONG"`。muse-vmの受信側`:8090/health`・Museの`:8080/health`も200 |

---

## 提案（未実施）

1. 出口の数を表にしてSPECに置く（本体のDO、muse-monitorのDO、デモコンテナのtailscaled）。デモコンテナの経路はWorkerを通らないので、1章の「Workerの出口」とは分けて書く。
2. libのworkerの状態に、鍵の有無（値は出さない）を出す口を足すかを決める（新しい設定を足さずにできる範囲で）。

---

## 確かめていないこと

- 本体のWorker・muse-monitorからmuse-vmへの実経路（今回は通していない）。
- muse-monitorの契約テストの中身。
