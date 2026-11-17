# NOTICE: receiver.py の鍵照合は「稼働中実装」を正とする

日付: 2026-11-18（JST）
**対象**: `muse/samples/receiver.py`（muse-vm の :8090 で稼働し、muse-monitor が呼ぶ受信側）の鍵照合の実装が、upstream（commit 2ba0f23）と muse-vm 上の稼働中実装とで分岐していた件。利用者の決定（2026-11-18）により、**今正常に稼働しているほう（muse-vm の実装）を正**とし、upstream をそちらへ寄せた。本書は、その統一の根拠と、失われた診断手段の代替を記録する。

## 分岐していた2つの実装

| 項目 | 稼働中実装（正とした側） | upstream 実装（2ba0f23、取り下げ） |
|---|---|---|
| 鍵の読み元 | `~/.config/muse-receiver.env` の `TS_API_KEY`。`--key-env-file` で変更可 | 同じファイル（固定） |
| 鍵が無いとき | 起動はする。gated な経路（`/monitor/*`・`/queue`）だけが 503 `receiver_key_missing` | 起動自体を拒否（終了コード 2） |
| 鍵の不一致 | 401 `{"error": "unauthorized"}` のみ | 401 に期待側・提示側の指紋を含める |
| `/health` | `{"status": "ok"}` のみ | 鍵の指紋 `keyFingerprint` を含める |
| env ファイルの解釈 | 行頭が `TS_API_KEY=` の行だけ、最後の代入が勝つ。空白は落とす。引用符・`export` は解釈しない | 引用符・`export`・空白を解釈する |
| Bearer の照合 | `Bearer <鍵>` の完全一致のみ（前後の空白は不一致） | 前後の空白を許容する |

## 稼働中実装を正とした根拠（実経路での検証記録）

- 2026-11-16 の muse-monitor セキュリティ強化（SPEC.muse-monitor.security.hardening）で muse-vm に導入し、以後 :8090 で稼働し続けている。
- gate のテスト 14/14 合格（2026-11-16）。`/monitor/diag` は鍵ありで 200、鍵なしで 401 を実測。
- receiver-watch（3分間隔、複合条件）による再起動と回復確認が、この実装の前提（鍵なしでも起動し、gated 経路だけ 503）で運用されている。
- 鍵の役割分離: 受信側の鍵は `TS_API_KEY` のみ。`TS_AUTHKEY`（Tailscale の参加鍵）は受信側の鍵として扱わない（receiver.py 内のコメント REQ-SEC-001/002/004）。

## 失われるものと、その代替

upstream 実装の指紋診断（401 と /health に鍵の指紋を出す仕組み）は、稼働中実装には無い。統一により、**鍵の不一致が起きても、応答からはどちらの鍵が違うか分からない**。

代替は、設定時点の指紋を記録しておくこと:

- 現在 muse-vm に設定されている受信側鍵の指紋は `7b3d979c`（2026-11-16 に設定・実測。指紋 = 値の SHA-256 先頭8桁）。
- 不一致が疑われるときは、送信側（muse-monitor の `TS_API_KEY`）の指紋とこの記録を突き合わせる。応答ではなく台帳で切り分ける。

## テストの扱い

`test/muse_samples_test.py` の receiver 関係のテストは、upstream 実装の振る舞い（指紋、起動拒否、引用符の解釈、空白の許容）を書いていたため、稼働中実装の振る舞いへ書き換えた（42件すべて合格、2026-11-18）。振る舞いを戻すときは、この NOTICE と SPEC.muse-monitor.security.hardening の REQ-SEC 群を先に直すこと。
