# tree-view SPEC評価連携の検証記録

## 実装範囲

既存AIチャットの固定Codex会話とコンソール送信許可を使い、構造化されたSPEC評価依頼を中継する。別モデルや本体WorkerのAI問い合わせAPIへは送らない。

受付と保存済みEVALを区別し、同一受付の再送防止、OSロック、永続receipt、実ファイルのメタデータ・ハッシュ照合を実装。関連付けは同名接尾辞、または説明付き接尾辞と明示的SPEC参照。設定・反映方法はSPEC.lib.20261028.spec-eval.mdを参照。

## 確認できた範囲

- `spec_eval_test.py`: 7件成功。不存在、既存EVAL、説明付き既存EVAL、SPEC変更、重複作成抑止、再起動後の参照、送信不明時の非再送、パス・symlink・Git origin検証、完成後の改変・削除の検出。
- `chat_observer_test.py`: 6件成功。実Unix WebSocketで既存`turn/start`経路を通し、テスト用app-serverが保存したEVALの検出まで確認。実LLMは使用していない。
- `chat_http_stream_test.py`: 14件成功。観察と送信の権限分離、Origin拒否、送信許可の失効、構造化リクエストの中継を含む。
- 既存の`chat_*test.py`全体43件は成功した実行がある。ただし再実行では未変更の`chat_websocket_test.py::test_disconnect_stops_polling_without_resubmit`が1回失敗した（callsが1から2へ増加）。全実行で安定して成功したとは報告しない。
- Nodeの既存`chat_*test.mjs`は40件中38件成功。Cookie復元の2件が`location is not defined`で失敗。同じ失敗を変更していない元の`/root/lib`でも再現した。session.mjsとそのテストはこの変更に含めない。
- PythonとJavaScriptの構文確認、git diff --check。

## 未確認と反映状態

本番サービスの再起動、公開配信、環境変数の実配置、実CodexによるSPEC評価は未実施。Dockerビルドは未実施。モデルの評価内容の妥当性や、本番の全チェックアウトと固定会話の対応は上記テストでは保証しない。
