# mygwストリーム投稿：アドホック対応と恒久設計

記録日: 2026-11-04。対象はmygwの会話ストリーム閲覧・投稿。ユーザーの承認を受けて実施した暫定対応であり、恒久設計として採用したものではない。

改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。要件の番号（`REQ-CS-…`）と、mygwのobserverがClaude版に替わった今の状態（末尾の「2026-11-19の現状」）を足した。11-04・11-05の記録は変えていない
評価: [`EVAL.lib.20261104.console-stream-adhoc.opus-5.5.20261119.md`](EVAL.lib.20261104.console-stream-adhoc.opus-5.5.20261119.md)
定期的な見直し: このSPECは[`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す

## 今回のアドホック対応（実施済み）

mygwのobserverはSSH上のCodexと同じ会話の履歴を読んでいた。しかし閲覧用App Serverではその会話がnotLoadedで、turn/startはthread not foundとなった。投稿時だけthread/resumeする修正を加えたところ、元のSSH Codexが書き込みを所有しているため、already has an active writerで拒否された。

この問題を回避するため、元の会話をthread/forkで複製し、履歴を引き継いだ**別の投稿用会話**を作成した。privateなobserver設定を原子的に更新し、mygwストリームの閲覧・投稿先をその会話へ切り替えた。元のSSH会話のロック解除・停止・書き換えは行っていない。

- 投稿用会話の表示名は「mygw 投稿用（SSHとは別の会話・以後同期なし）」とし、ストリームにもサーバーから取得した会話名を表示する。
- 引き継ぐのは分岐時点の保存済み履歴。分岐後のSSH会話と投稿用会話は双方向にも片方向にも自動同期しない。
- Webからの投稿は投稿用会話で実行され、現在のSSH会話への入力にはならない。
- 閲覧だけではthread/resumeやturn/startを呼ばない。読み込みが必要な場合は認証済み投稿時に固定された対象IDだけをresumeする。
- writer競合時はロックを壊したり別会話へ黙って再送したりせず、console_in_use（HTTP409）を返す。
- 既存のHMAC認証・Origin制限・投稿用の期限付き許可は維持する。ブラウザから任意の会話IDやRPCを指定できるようにはしない。
- /neko askgkの独立ジョブ送信とは別の経路であり、ストリーム投稿先の変更がaskgkの会話継続を意味するわけではない。

## 暫定対応の制約とアンチパターン

分岐自体は明示的な別作業としては利用できる。しかし、別の会話を同じ会話の入出力であるかのように見せる運用は避ける。履歴の分岐による認識の不一致、SSHとWebで異なる応答・作業が走ること、設定先の取り違えが生じるためである。

会話履歴を複製してもファイルシステムは隔離されない。SSH側と投稿用会話の実行が同じ作業ディレクトリを変更すると競合し得る。別会話になったことを作業環境の分離と同一視しない。

今回の切替は現コンテナの設定と稼働ファイルに適用した。Dockerイメージへは未反映で、コンテナ再作成後の会話ストア・設定の永続性は保証していない。

## 恒久設計（未実装）

一つの実行サーバーが対象会話の書き込みを管理し、WebとSSH側の対応クライアントがそのサーバーへ接続する。履歴の閲覧・投稿・実行中の追加入力は同じ会話IDへ向ける。独立したSSH TUIと別App Serverが同じ会話へ同時に書く構成にはしない。現在のSSH TUIをそのまま共通サーバーへ接続できると確認したわけではなく、対応クライアントまたは起動方式の変更が必要。

恒久化には以下を満たす必要がある。

1. 会話ID・実行サーバー・書き込み所有者の正とする設定を一元化する。
2. 複数クライアントからの投稿順序、実行中の追加入力、同一要求の重複排除、切断後の結果照会を定義する。応答が失われた投稿を別会話へ無条件で再送しない。
3. 閲覧権限と投稿権限を分離し、認証・失効・期限を全経路で同じように適用する。
4. 閲覧画面を閉じた状態やバックグラウンド確認でコンテナ・AI実行を起動しない。
5. 会話ストアと選択設定の永続化、再起動後の復元、所有権競合時の安全な停止を検証する。
6. SSHとWebの双方から同じ会話を読み、順序・認証拒否・再接続・競合・通信失敗を含むテストで確認する。

## 移行・復元

恒久設計へ移る際は投稿を一時停止し、処理中要求の結果を確定してから、利用する会話と所有者を明示的に選ぶ。分岐した履歴を自動マージしたり、投稿用会話を削除して元の会話へ戻したりしない。必要な履歴を保持し、切替前後のID・理由・日時をprivateな記録へ残して、observerの選択を原子的に置き換える。SSH会話を選び直すだけではwriter競合の解決にはならない。

元のobserver設定と分岐のreceiptはroot専用 `/root/.cache/console-post-fix-20261104/` に保存。秘密情報・認証トークン・履歴本文はこのSPECへ記載しない。

## 実測結果

- 専用会話作成とobserver切替後、公開mygwの投稿許可APIはHTTP200。
- 公開 `/lib/api/chat/console` はHTTP200・accepted=true。
- observer経由で専用会話のAI回答 `CONSOLE_POST_OK` を確認。受理だけを成功扱いしていない。
- Python48テスト成功。生成ブラウザモジュールのnode --check成功。
- Nodeの既存40テストは38成功、未変更のsession cookieテスト2件がlocation未定義で失敗。全テスト成功とは扱わない。
- 実利用者のログイン済みブラウザからの投稿操作と、コンテナ再作成後の復元は未検証。

App Serverの履歴分岐と投稿仕様の根拠: [公式OpenAIドキュメント](https://learn.chatgpt.com/docs/app-server)。診断経緯は [REPORT](REPORT.console-post.20261104.md) を参照。


## 2026-11-05: 一本化方針への移行

ユーザー指定により、別の投稿用会話で競合を回避する運用は採用しない。現在ENVのCODEX_THREAD_IDと依頼本文を読み取りAPIで照合し、observerの参照先をその同一会話へ設定した。過去のfork履歴は削除も自動マージもしていない。

投稿時にthread/resumeがactive writerで拒否された場合は、その会話IDへCodex 0.166.0のnative `thread/queue/add` で入力を追加する。writerのロックは維持し、fork・別IDへの再送・queue登録後のturn/startは行わない。返されたqueuedSubmissionのID・clientUserMessageId・inputを確認できたときに限りaccepted/queuedを返す。エラーや不明な応答を自動再試行しない。観測クライアントからqueue/addは呼べない。

画面はaccepted=trueを検証し、queued=trueなら「この会話の送信待ち」と表示する。受付は応答完了を意味しない。現在のwriterが入力を取り込むまでは待機する。所有プロセスの終了・再起動後を含む自動復帰と、通信断後の利用者による再投稿の重複排除は未保証。

実測では公開console POSTのaccepted=true/queued=trueと、同じENV会話のnative queue/listに一致する入力が1件だけ存在することを確認した。既存writerが処理中のため、この検証時点で取り込み・assistant応答は未確認。詳細は本体Workerの20261105 NETWORK REPORTを参照。

### 後続ターンでの配信確認

同じ会話でテスト投稿を実受信し、assistantのSTREAM_POST_OK_20261105応答を公開observer配信でも確認した。native queueの該当件数は0となった。前節の取り込み・実応答未確認は解消。実ブラウザ操作・再作成後の復元・通信断時の手動再送の重複排除は引き続き未検証。

## 要件の番号（2026-11-19に付与）

11-05の一本化の方針を正とする（11-04の別会話の運用は採用しない）。

| 番号 | 要件 | 本書の節 |
|---|---|---|
| REQ-CS-1 | 投稿は閲覧中と同じ会話IDへ向ける。別の会話への分岐・別IDへの再送はしない | 2026-11-05 |
| REQ-CS-2 | 書き込み中の会話（active writer）には、ロックを壊さず`thread/queue/add`で入力を足す（Codex版）。キューの登録を確かめたときだけ`accepted`・`queued`を返す。エラーや不明な応答は自動で送り直さない | 2026-11-05 |
| REQ-CS-3 | 競合を解決できないときは`console_in_use`（HTTP 409）を返す | 今回のアドホック対応 |
| REQ-CS-4 | 閲覧だけでは`thread/resume`・`turn/start`（Claude版では`claude -p`）を呼ばない | 同上 |
| REQ-CS-5 | HMAC認証・Origin制限・投稿用の期限付き許可を保つ。ブラウザから任意の会話IDやRPCを指定させない | 同上 |
| REQ-CS-6 | 画面は`accepted=true`を確かめ、`queued=true`なら「この会話の送信待ち」と表示する。受付を応答の完了として扱わない | 2026-11-05 |

## 2026-11-19の現状

- **mygwのobserverは、Codex版からClaude版（`claude/ops/chat_observer_claude.py`）に替わっている。** 本体のdemoコンテナの起動処理が、`restore-claude-host.sh`で元のobserverを止めてClaude版を起動する（2026-11-13〜）。監視対象は`workspace:/root`（そのプロジェクトで最新のClaude Codeのセッション）。
- Claude版の投稿は、`claude -p --resume <session> -- <text>`を監視中のセッションのcwdで起動する。同じ会話IDへ向ける点（REQ-CS-1）は同じ。ただし、**Claude Codeには`thread/queue/add`に当たる仕組みが無い**。人が操作中のセッションへ送ると、2つのプロセスが同じ記録に書く（`claude/SPEC.claude.20261102.md`のREQ-CL-13）。REQ-CS-2はCodex版にだけ当てはまる。
- Codex版の実装（`ops/chat_observer.py`の`thread/resume`→`console_in_use`→`thread/queue/add`）と、HTTP側の409（`ops/chat_http_stream.py`）は11-05のまま残っている。
- 恒久設計（6項目）は未実装のまま。

## 改訂の記録

| 日付 | モデル | 箇所 | 内容 | 根拠 |
|---|---|---|---|---|
| 2026-11-19 | opus-5.5 | 冒頭・末尾 | 要件の番号と、observerがClaude版に替わった今の状態を追加。11-04・11-05の記録は変えていない | 稼働中のプロセス（`chat_observer_claude.py`、`LIB_CHAT_CLAUDE_SESSION=workspace:/root`）、`restore-claude-host.sh`、`git grep queue/add ops/` |
