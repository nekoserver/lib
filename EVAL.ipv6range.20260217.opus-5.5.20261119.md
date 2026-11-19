# 評価: ipv6range.shtml（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.ipv6range.20260217.md`](SPEC.ipv6range.20260217.md)（2026-11-19の改訂版、SHA256 `c521d6da924aa5af5d1f833d477cc40865c8d68a323939ba41f5a678a9b7b573`）
評価対象: `nekoserver/lib`の`main`（`592f438`）の`ipv6range.shtml`（最後の変更は`f8f8cf6`、2026-02-16）と、本体のdemoコンテナの内部Apache（`127.0.0.1:8445`）・公開Apache（8443）での動作
区分: [`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

---

## 総合

7つの要件をすべて満たす。base64で埋め込んだPythonのコードを復号し、SPECの4章の流れと1行ずつ一致することを確かめた。実際のApache（8445）で4通りの入力を送り、出力はSPECの表どおりだった。自動テストは無い。

---

## 要件ごとの評価

| 要件 | 判定 | 根拠（8445への`GET`、`X-Forwarded-For`を指定） |
|---|---|---|
| REQ-IP6-1 | 充足 | どの入力でも1行目が`HTTP_X_FORWARDED_FOR=<生の値>`、未設定なら`HTTP_X_FORWARDED_FOR=`。ファイル末尾の改行による空行が3行目に付くが、出力は2行 |
| REQ-IP6-2 | 充足 | `2001:db8:1234:5678::1, 10.0.0.1` → 先頭のIPだけを使った |
| REQ-IP6-3 | 充足 | 同上 → `2001:db8:1234:5678::1,2001:db8:1234:5678::/64` |
| REQ-IP6-4 | 充足 | `203.0.113.1` → `203.0.113.1` |
| REQ-IP6-5 | 充足 | `garbage` → `N/A`、未設定 → `N/A` |
| REQ-IP6-6 | 充足 | `<!--#exec cmd="printenv \| python3 -c ...base64..."-->`。復号したコードは`printenv`の出力を標準入力から読む |
| REQ-IP6-7 | 充足 | 公開（8443）は403、内部（8445）は200。8445の`010-lib.conf`は`Options +Includes +ExecCGI` |

---

## 提案（未実施）

1. 4通りの入力の出力を確かめる自動テスト（`printenv`の代わりに環境を渡して、復号したコードを動かす）。
2. 例外を受けるのが素の`except:`で、`KeyboardInterrupt`なども`N/A`にする。実害は無いが、`except ValueError:`に絞れる。

---

## 確かめていないこと

- 管理者の入口（本体ワーカー → `server.js` → 8445）を実際に通したときの`X-Forwarded-For`の値。今回はコンテナの中から8445へ直接送った。
