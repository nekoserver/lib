再協議のまとめです。既存合意は維持し、残差のみ整理します。

(1)停止要因の分離
・authRequired：:unrestricted診断でprofile_verified: requireとともに到達。SDKがホストの認証ゲートまで進んだ観測であり、成功ではありません。
・reviewer不可：:auto-reviewは「自動レビュアーが利用不可」で拒否され、profile_not_appliedで失敗。認証なしのためとの推定はありますが未検証です。
・必要条件：META_API_KEY設定後に:auto-review実ターンを再試行し、拒否が消えるか観測すること。消えなければ認証とは別の要因（モデル／ホスト能力）とし、META_API_KEYだけで解消するとは断定しません。

(2)短い段取り（コード追加なし）
①到達性読取診断：担当は運用者。別ノードから:8090/health、Worker /statusでRunningを確認。合格は/health 200とRunning。:8080と同方式という類推のみで、:8090自体は未確認です。
②必要条件確認：担当は運用者。META_API_KEYとWorker側3 secretの設定有無、deploy済みを確認。合格は設定の存在確認と/status Running。
③1回の実SDKターン：担当は運用者。:auto-reviewで最小指示。合格はターン正常終端・回答・差分・確認結果。

(3)requestId・保存結果
・既存保証：受信側は応答前にreceiver/jobs/<job_id>.jsonへ保存し、GET /code/status/<job_id>で再読可能。結果不明時はdelivery_unknownで保存し、無条件再送・自動フォールバックなし。ターン直列化。
・追加確認：Worker側requestIdと受信job_idの対応、Worker経由での状態再読、重複要求時の扱い（新規ジョブか同一ジョブか）は未測定で保証なし。実ターン時に観測して区別します。

(4)preprint案の修正
・preprint 0.1.2は後日の画面確認の補助にとどめ、単発検証の前提にしません。libはDraft PR119、本体PR準備中という別系統として扱います。

次は①〜③の3工程へ収束させます。git保存先の回答は未取得のため再送しません。
