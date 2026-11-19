# 評価: lib/muse の読み取り用スクリプト（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.scripts.md`](SPEC.scripts.md)（2026-11-19の改訂版、SHA256 `0d980ae35c90f22a5daf712a57baeb56dc980a919f4c2bfda3469777a0d84af4`）
評価対象: libの`main`（`592f438`）の`muse/`、本体のdemoコンテナの内部Apache（8445）、muse-vmの受信側（`:8090/health`だけ）
区分: [`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

スクリプトと受信側のサンプルは、改訂したSPECのとおりに動く（テスト73件中72件が通過。落ちた1件は環境の差）。改訂の前のSPECは、2026-11-18の受信側の変更（`7399ca0`）と`hooks.sh`の追加（`7fb2b20`）に追いついていなかった。`hooks.sh`は、6章の決まり（README・断片・SPECを同時に直す）を守らずに入り、テストも漏れを落とせていない。

| 要件 | 判定 |
|---|---|
| REQ-MS-1〜3・5〜7 | 充足 |
| REQ-MS-4 | 充足（`hooks.sh`は改訂で表に足した。テストの対象外） |
| REQ-MS-8 | 未充足（`hooks.sh`） |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-MS-1・2 | 充足（テスト） | `test/muse_scripts_test.py`の原則の検査（状態を変えるコマンド、tailscale CLI、外部への接続）が通過。`hooks.sh`は対象の一覧に無いが、中身は`python3`でファイルを読むだけ（`rm`・`kill`・`systemctl`・`tailscale`を含まない、`grep`で確認） |
| REQ-MS-3 | 充足 | シェバンのある`muse/`のファイルで`100644`のものは0件（11-18のEVALの未充足は`56e9aad`で直った）。`tailnet-health.sh`は`100755` |
| REQ-MS-4 | 充足（テスト） | 2章の表のスクリプトはテストで出力を確かめている。`GitHeadsTest`だけが落ちる: テストが`PATH`を`/usr/bin:/bin`に絞り、このコンテナのgitは`/usr/local/bin/git`なので、gitが見つからず出力が空になる。`HOME`を一時ディレクトリにして`dash`で直接動かすと、SPECの形（`workspace/proj [main] <hash> <件名> (dirty: 0, unpushed: ?)`）で出た |
| REQ-MS-5 | 充足 | 8445で`index.shtml`が200、`tailnet.shtml`は`(access denied)<br>`（エスケープと`<br>`の付与）。`hooks.sh`の断片は無い（REQ-MS-8） |
| REQ-MS-6 | 充足 | `test/muse_samples_test.py`が通過（`7399ca0`の後の形: `/health`は`{"status": "ok"}`、鍵が読めなければ503 `receiver_key_missing`、401は`{"error": "unauthorized"}`）。muse-vmの`:8090/health`の実測は200 `{"status": "ok"}`で、改訂後の4章と一致（改訂前の`keyFingerprint`は無い） |
| REQ-MS-7 | 充足（テスト） | 同上のテスト（同時実行の上限・到着順・あふれ・待ち時間・まとめ・使い回し・`/queue`） |
| REQ-MS-8 | 未充足 | `hooks.sh`（`7fb2b20`）は、READMEの表・`dashboard/`の断片・SPECの2章のどれも直さずに入った。`READ_ONLY_SCRIPTS`が固定の一覧なので、テストが漏れを落とさない |

---

## 提案（未実施）

1. `hooks.sh`を、READMEの表と`dashboard/`の断片（または「断片を置かない」理由）に足し、`READ_ONLY_SCRIPTS`に入れる。テストを、`muse/*.sh`から`sdk-*`を除いた全部と`READ_ONLY_SCRIPTS`が一致することを確かめる形にすると、次の漏れを落とせる。
2. `GitHeadsTest`の`PATH`に、`shutil.which('git')`のディレクトリを足す。
3. `daemon-check.sh`・`exec-log.sh`・`pending.sh`・`diag.sh`の出力の形を、このSPECか`SPEC.md`のどちらかで定める。
4. `SPEC.lib.tailnet-health.shtml`をlibに入れるか、参照を実在する文書に直す。

---

## 確かめていないこと

- muse-vmの実環境でのスクリプトの実行と、受信側の`/monitor/*`・`/queue`（鍵が要るため、今回は`/health`だけ）。
- `receiver-check.sh`（muse-vmで動かすもの）。
