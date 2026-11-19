# 既存Codex会話を使ったtree-viewのEVAL作成

作成日: 2026-10-28（コミット`a9c62d5`）
改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。要件の番号（`REQ-SE-…`）と、今の稼働の状態（末尾の「2026-11-19の現状」）を足した。経路・保存の仕様は変えていない
評価: [`EVAL.lib.20261028.spec-eval.opus-5.5.20261119.md`](EVAL.lib.20261028.spec-eval.opus-5.5.20261119.md)
定期的な見直し: このSPECは[`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す

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

## 要件の番号（2026-11-19に付与）

| 番号 | 要件 | 本書の節 |
|---|---|---|
| REQ-SE-1 | 経路は埋め込みページ → `POST /lib/api/chat/spec-eval` → observerのソケット。inspectは観察セッション、createは投稿セッションが必要。Originと失効をサーバーで再検証する | 経路と認証 |
| REQ-SE-2 | 対象は`LIB_SPEC_EVAL_REPOSITORIES`（省略時は既定の5リポジトリ）だけ。Gitのoriginが一致すること、symlink・リポジトリ外への脱出を拒否する | 正とするデータと保存 |
| REQ-SE-3 | EVALはSPECと同じディレクトリに同じ接尾辞で作る。説明付き接尾辞のEVALは、本文にSPECへの明示的な参照があるときだけ対応付ける | 同上 |
| REQ-SE-4 | 受付は`/var/lib/lib-chat-observer/evaluations/<SHA256>.json`に保存してから1回だけ送る。flockで競合を拒否し、自動で再送しない。破損はfail closed | 同上 |
| REQ-SE-5 | 完成は対応ファイルと監査メタデータを実際に読んで確かめ、ハッシュを保存して後の改変を検出する | 同上 |

## 2026-11-19の現状

- 実装は`ops/spec_eval.py`（10-28から変更なし）。元のobserver（`ops/chat_observer.py`）と、Claude版（`claude/ops/chat_observer_claude.py`）の両方が`spec-eval`を受け付ける。
- 本体のdemoコンテナ（mygw）で動いているのはClaude版のobserver。createは、監視中のClaude Codeのセッションへ`claude -p --resume`で依頼を送る。送られたセッションが対象リポジトリを読み書きする許可を持たないと、EVALの保存まで完了しない（`claude/SPEC.claude.20261102.md`の「未確認・未対応」）。
- 既定の対象は本体・dynamicneko・rust-worker-sqlx-d1・rails-root・railwayの5つ。**lib自身は入っていない**ため、libのSPECはtree-viewからは評価できない（inspectは`evaluation_unavailable`）。libのSPECの評価は[`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順で行う。
- 「反映」の1〜5のうち、dynamicneko側の反映とCodexの固定会話の接続は、このコンテナでは確かめていない。

## 改訂の記録

| 日付 | モデル | 箇所 | 内容 | 根拠 |
|---|---|---|---|---|
| 2026-11-19 | opus-5.5 | 冒頭・末尾 | 要件の番号と、今の稼働の状態を追加。本文は変えていない | `git log ops/spec_eval.py`（10-28の1件だけ）、observerへのinspectの実測 |
