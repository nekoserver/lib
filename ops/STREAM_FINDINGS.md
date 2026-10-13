# 会話の閲覧とストリーム通信の知見

## 今回の到達点

同じAIチャットページで、SSE・WebSocket・NDJSON・JSON Text Sequenceを
切り替えられる。初期表示は「この会話（閲覧のみ）」とSSE。
既存のHMACキーで表示を開始し、会話・作業の更新・作業状況を確認する。
メッセージの送信、会話の再開・分岐、モデル設定の変更は今回の閲覧接続に含めない。

「別のAI実行」は従来の独立したCodex／Claudeキューを使う。
その入力は、この会話には送られない。通信方式を変えてもジョブIDを使った
再接続は参照だけで、同じプロンプトを再実行しない。
「比較デモ」はキー不要で固定文章を分割配信し、AIを実行しない。

## 接続の構成

```text
この会話のCodex App Server（既存プロセス）
  ↕ WebSocket over root専用Unix socket
閲覧専用observer（root、固定スレッド、読むメソッドのみ）
  ↓ /run/lib-chat-observer/observer.sock（root:www-data、0660）
配信サーバー（www-data、127.0.0.1:8091 / :8092）
  ↓ Caddy → Cloudflare Tunnel → HTTPS
ブラウザー（SSE / WebSocket / NDJSON / JSON-seq）
```

observerは `thread/read` と `thread/turns/list` を約1秒間隔で呼ぶ。
`thread/resume`、`turn/start`、`turn/steer`、スレッドの設定変更は呼ばない。
会話を読むだけで新しいAI実行や課金対象のモデル呼び出しは起動しない。
接続先のUnix socketとスレッドはroot管理の環境設定で固定し、ブラウザーから
任意のスレッドやRPCメソッドを指定できない。

公開するのはユーザーのテキスト、AIの表示用メッセージ、状態、ツールの種類だけ。
内部推論、ツール引数、コマンド本文、ツール出力、認証データは表示用データに含めない。
画面は最近40メッセージを対象にし、1メッセージ8192文字・全体49152文字を上限とする。
長い本文は上限で省略される。過去の全履歴閲覧やページングは今後の拡張候補。

## 通信方式と生成側は別

| 方式 | ブラウザーでの受信 | 区切り | 今回の用途 |
| --- | --- | --- | --- |
| SSE | fetch + ReadableStream | event/data、空行 | 初期選択。サーバーからの更新配信 |
| WebSocket | WebSocket | メッセージ | 認証と操作要求、更新受信 |
| NDJSON | fetch + ReadableStream | 1行のJSON | HTTP上の簡単なレコード配信 |
| JSON Text Sequence | fetch + ReadableStream | RS文字 + JSON + LF | JSONの境界が明示的な配信 |

SSEはPOSTレスポンスとして受信する。EventSourceでは任意の認証ヘッダーを
付けられないため、既存のHMAC署名を送れるfetchを使う。
EventSourceの自動再接続は利用せず、接続の終了と再接続を画面で制御する。

ネットワークのチャンク境界は文字・JSON・SSEイベントの境界と一致しない。
UTF-8の途中で分割されてもTextDecoderで復元し、各方式のレコード境界まで
保持してから解析する。受信停止は接続の中断であり、既存キューのCLI実行を
キャンセルしない。

ブラウザーへの配信がストリームでも、生成側のAPIが完成後の回答しか返さなければ、
回答は一括でしか表示できない。従来のCLIキューはこの構成のまま。
今回の「この会話」表示は履歴・状態の1秒サンプリングであり、トークンごとの
通知を直接転送するものではない。メッセージ保存のタイミングにも影響される。
一方、比較デモのdeltaは完成後の回答を見せかけで分割するのではなく、
テスト用の固定データを時間差で実際に送る。AIの生成とは明確に区別する。

## 運用でわかったこと

- CaddyのHTTPストリーム用proxyに `flush_interval -1` を設定する。
  レスポンスは `no-store, no-transform` にして不要な蓄積・変換を避ける。
- SSEのheartbeatで、会話が静かな間も接続を維持し受信状況を確認できる。
- 画面の到着時間は認証・ネットワーク・サーバー・生成待ちを含む観測値。
  1回のデモだけでプロトコルの速度優劣を断定しない。
- CloudflareにCSSの旧版が残ることがあった。変更したCSSは新しいファイル名で配信する。
- VMスリープで独自プロセスは停止する。observerと配信サーバーを復帰時の起動手順に含める必要がある。
  このVMでは既存のstart-lib-webに起動処理を追加する。platform管理プロセスは変更しない。
- rootのCodex制御socketをそのまま公開しない。www-dataには制限されたobserverのsocketだけを渡す。

## 設定・導入

依存関係は `ops/chat-websocket-requirements.txt` に固定。
`www-data`から実行できるPythonを使った `/opt/lib-chat` へインストールする。
既存の `LIB_CHAT_ORIGINS` とHMACキーの設定は維持する。
root所有0600の `/etc/lib-chat.env` に、表示する会話の
`LIB_CHAT_APP_SOCKET`（既存app-serverのUnix socket）と
`LIB_CHAT_THREAD_ID`（固定スレッド）を設定する。
環境固有のsocket・スレッド・認証情報はGitに保存しない。

systemdを使う環境では `chat-websocket.service` に加えて
`chat-http-stream.service` と `chat-observer.service` を導入する。
systemdがないVMでは同じコマンドを既存の起動処理からdetachして起動する。
observerは `/tmp` の既存socketを使うためPrivateTmpで隔離しない。

`origin-proxy`スニペットでは、未指定パスのApache proxyより前に追加する：

```caddyfile
@chat_ws path /lib/api/chat/ws
reverse_proxy @chat_ws 127.0.0.1:8091
@chat_stream path /lib/api/chat/sse /lib/api/chat/ndjson /lib/api/chat/jsonseq
reverse_proxy @chat_stream 127.0.0.1:8092 {
    flush_interval -1
}
```

既存のsite-level logを含むスニペットをhandleの中へimportすると検証に失敗する。
既存listenerのtop-level importを維持し、設定をvalidateしてからWeb用Caddyだけ再起動する。

## 今回の検証

- Python側18件、JavaScript側17件のテストが成功。
  認証、デモ認証で会話を読めないこと、readonly RPCの制限、privateデータの除外、
  UTF-8分割、SSE/NDJSON/JSON-seq解析、再送防止、途中切断を確認した。
- 公開ページをChromiumで開き、4方式すべてでデモの文章が完了前に増えること、
  同じ会話が表示されること、heartbeat、受信停止、375px幅、JSエラーなしを確認した。
- 確認中にAI実行は送信していない。既存会話の読み取りと固定デモだけで検証した。

## 次に拡張するなら

まず今回の閲覧と測定結果を確かめる。双方向の操作は次段階。
将来は専用の認証・権限・同時操作制御を設計してから、同じスレッドへの送信、
作業の中断、生成中deltaの購読、履歴ページングを検討する。
現在の閲覧接続にmutating RPCを追加するだけの変更にはしない。

参考：
[Codex App Server公式仕様](https://learn.chatgpt.com/docs/app-server)、
[aiohttp StreamResponse](https://docs.aiohttp.org/en/stable/web_reference.html#streamresponse)、
[SSEのイベント形式](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)、
[RFC 7464](https://www.rfc-editor.org/rfc/rfc7464)。
