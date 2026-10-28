# 既存Codex会話を使ったtree-viewのEVAL作成

## 経路と認証

親tree-view → 許可済みoriginのconversation-embed → `POST /lib/api/chat/spec-eval` → observer Unix socket → 既存固定Codex会話の`turn/start`。

inspectには観察セッション、createには既存コンソール送信セッションが必要。Originと失効をサーバーで再検証する。親ページへトークン・HMACキーを公開しない。既存のAI別ジョブ実行や本体Workerは経由しない。

## 正とするデータと保存

`LIB_SPEC_EVAL_REPOSITORIES`は`{"nekoserver/dynamicneko":"/root/dynamicneko", ...}`形式のJSON。省略時はtree-viewの既存5リポジトリに対する`/root/<repo>`。observerと接続Codexの双方から同じチェックアウトを参照できることが必要。異なる配置は環境変数で明示する。Git originが対象repositoryと一致することを検証し、任意URLのcloneや任意パスの参照は許可しない。

SPECと同じディレクトリに同じ接尾辞のEVALを作成する。既存の説明付き接尾辞のEVALは本文に対象SPECへの明示的な参照がある場合に対応付ける。SPEC/EVALのsymlinkとリポジトリ外への脱出を拒否する。

受付情報の正は`/var/lib/lib-chat-observer/evaluations/<repo+pathのSHA256>.json`。ID、対象、受付日時、SPEC SHA256、受付HEAD、状態、完成時刻・ファイルハッシュを保存する。モデルにはSPECとコードの評価、根拠、実施検証、未確認事項、原子的なファイル保存を指示する。既存EVALの上書き・コード修正・push・デプロイは依頼しない。

受付を保存してから一度だけ送信。OSのflockで複数プロセスの競合を拒否し、送信結果不明でもreceiptを保持して再送しない。再起動後も再送しない。作成完了は対応ファイルと監査メタデータを実読して確認する。完成ファイルのハッシュと作成確認日時は保存し、後の改変を検出する。既存の未追跡EVALの作成日時は不明とし、mtimeを作成日時と偽らない。新規の原子的保存は最初に観測した完成ファイルのmtimeを作成日時として記録する。

受付がpendingのままでもモデル実行成功とは限らない。会話の失敗、タイムアウト、SPEC変更、送信不明は自動再試行しない。破損状態はfail closed。復旧時にはreceipt・EVAL・SPECを退避して会話と照合し、未保存／中断を確認後に管理者が受付を退避する。受付を黙って削除したり既存EVALを置換しない。

## 反映

1. `ops/spec_eval.py`をobserverと同じopsディレクトリへ配置。`chat_http_stream.py`と`chat_observer.py`を更新。
2. `chat-observer.service`を更新し、StateDirectoryの書き込み許可を反映。サービス定義のreload後にobserverとHTTPサービスを再起動。
3. `chat/app.mjs`とfingerprint済みアセット、`conversation-embed.html`を同時に配置。旧fingerprintは既存閲覧者のために保持。
4. 配置に応じてLIB_SPEC_EVAL_REPOSITORIESを設定。各Git originと固定会話の接続を確認。
5. dynamicneko側を反映。観察のみではボタン無効、送信許可後に有効、実保存後に日時表示になることを確認。

Dockerビルド、本番反映、実モデルによる評価の実行確認はこの仕様文書の追加だけでは完了としない。
