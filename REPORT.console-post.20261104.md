# mygwストリーム投稿の診断 — 2026-11-04

公開mygwで投稿許可POSTは200だが、console POSTは503を再現。observerが既存履歴を読むApp Serverでは対象がnotLoadedで、turn/startはthread not foundだった。公式仕様 https://learn.chatgpt.com/docs/app-server に従い、認証済み投稿でのみthread/read後に必要なら固定IDをthread/resumeする処理を追加した。閲覧処理の読み取り専用制約は維持。

実対象のthread/resumeは「already has an active writer」で拒否された。現在のSSH Codexが使用する同一会話であり、別App Serverが読み取れる履歴と書き込み所有権は別。既存writerのロックは解除せず、別threadへの自動切替もしない。投稿先を履歴継承した専用会話へ変更するか、既存SSH会話への入力が必要かをユーザーへ確認中。投稿機能は未復旧。

追加: writer競合をconsole_in_useとしてobserver→HTTP409→ブラウザへ通知し、503の一般エラーから区別。notLoadedを「会話終了」と断言する文言を修正。現コンテナのobserver・HTTP relayとfingerprint付きブラウザ資産を更新。短いHTTPプロセス起動直後の確認では非JSONが返ったため、起動後に再確認し、投稿許可200、投稿409 console_in_useを確認。入力を受理したとは報告しない。

Python48テスト成功。Node40テスト中38成功、今回変更していないsession cookieの2件がlocation未定義で失敗。生成appモジュールのnode --checkとgit diff --check成功。Dockerビルド・コンテナイメージ更新・本体Worker再配備は実施していない。旧ファイルのprivate backupは /root/.cache/console-post-fix-20261104/ 。再作成後にイメージへ自動反映する保証はない。

## ユーザー承認後の暫定復旧

履歴を引き継ぐ投稿用会話の作成についてユーザーの承認を得てthread/forkを実行。private sourceを原子的に切替。公開console API200・accepted=true、observerでAI回答CONSOLE_POST_OKを確認。表示名を「mygw 投稿用（SSHとは別の会話・以後同期なし）」とし、ブラウザにも会話名を表示する。元SSHの会話とは分岐後に同期しない。恒久設計ではなくアドホック対応として [SPEC](SPEC.lib.20261104.console-stream-adhoc.md) に制約・移行条件を記録。

## 解決扱いと初期設定テスト

ユーザー指示で本件を一旦解決として記録。投稿用会話への公開POST 200だけでなく、observerで固有応答 `CONSOLE_POST_OK` を確認済み。運用時は元SSH会話と投稿用forkを同じ会話として扱わず、画面上の会話名を確認する。

再発防止として、メインWorkerリポジトリの `containers/demo/NETWORK-RUNBOOK.md` と稼働コンテナ内の `/root/lib/ops/README.md` に手順を追加。`tunnels.rb`、WebSocket/SSE、observer、App Server等を新規・再設定・再配置した際は、初期設定後にsocket/ENV/認証済み各ストリーム/fixed observer/投稿/実応答の全確認を行い、REPORTへ結果を残す。起動、HTTP200、acceptedだけでは完了扱いにしない。AIターンを開始する確認は明示的な一回の投稿に限る。

残る未確認範囲: ログイン済み利用者の実画面操作、コンテナ再作成後の会話・設定の復元。
