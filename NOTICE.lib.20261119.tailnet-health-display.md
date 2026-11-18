# NOTICE: tailnet 区画の表示確認で出た3件と、SPEC 版3の不足

日付: 2026-11-19
対象: `muse/dashboard/tailnet.shtml` / `muse/tailnet-health.sh`（SPEC.lib.tailnet-health.shtml）
関連PR: nekoserver/lib#153（照合対象の X-Forwarded-User 切替）

2026-11-18 夜から 19 日未明にかけて、本番コンテナ（cf-demo）で tailnet 区画の
表示を確認した際に発生した事象と、切り分けで確定した原因を記録する。
いずれも SPEC 版3 が固定している範囲（スクリプトの振る舞いと README
サンプルの形）の外側で起きた。

## 1. 断片が空行になる（実行権限の喪失）

- 症状: `tailnet.shtml` の応答が空行のみ。`(access denied)` すら出ない。
- 原因: 配置された `muse/tailnet-health.sh` の実行権限が落ちていた
  （`-rw-r--r--`）。リポジトリでは +x 付きで管理されているため、コンテナへ
  置く過程で失われた。
- 空行になる理由: 断片は `#exec cmd="../tailnet-health.sh | sed ..."` の
  パイプラインで、スクリプトが実行できない場合のエラーは Apache のログ側へ
  流れ、sed には何も渡らない。SSI のエラー文も出ないため、無言で空になる。
  スクリプト自体には空を返す経路は無い（フラグ無しなら必ず
  `(access denied)` の1行を出す）。
- 確定方法: コンテナで `ls -la` の権限確認と、スクリプト単体実行
  （www-data でも実行できること）で切り分けた。
- 対処: `chmod +x`。他のスクリプトも同じ置き方で権限が落ちている可能性が
  あるため、一括確認の対象。

## 2. アカウント名を入れても変わらない（設定の置き場所の誤り）

- 症状: SetEnvIf の行に正規ユーザー名の実名を入れたのに、表示が変わらない。
- 原因: 編集したのは lib 側 README のサンプルであり、Apache の実設定では
  なかった。`grep -R 'MUSE_TAILNET_HEALTH_OK' /etc/apache2/` で、実設定の
  どこにも行が存在しないことを確認して確定した。README のサンプルは
  設定ではない。
- 対処: lib vhost（`sites-enabled/010-lib.conf`）の `</VirtualHost>` の前に
  `SetEnvIf X-Forwarded-User ^<実名>$ MUSE_TAILNET_HEALTH_OK=1` を入れ、
  Apache を graceful で再読み込みした。
- 確認結果（2026-11-19 00:08）: ヘッダ無しの直 curl では
  `(access denied)<br>`（設計どおり）、実名ヘッダ付きでは中身が表示された。
  ブラウザ（プロキシ経由）でも中身の表示まで到達した。

## 3. プロキシ経由の表示で文字化け

- 症状: ブラウザ（Worker プロキシ経由）で中身は出るが文字化けする。
  コンテナ直の curl では化けない。
- 確認済み: 経路の両プロキシ（Worker の proxy ハンドラとコンテナ
  server.js の `proxyToLib`）はどちらもバイト列の素通しで、変換は無い
  （コードで確認）。
- 未確定: 断片単体の応答には charset の宣言がどこにも無い（断片には
  meta を置けず、lib vhost に AddDefaultCharset も無い）ため、ブラウザの
  デコード推測が外れていることが候補。確定には認証済み応答のヘッダ実測が要る。

## SPEC 版3の不足（次回改訂で引き上げる項目）

版3の「保証範囲」第3層（本番配置は未保証）に落ちていたものを、前提と
受け入れ条件（AC: Acceptance Criteria、要件が満たされたかを判定する
具体的に確認できる条件）へ引き上げる。

1. 配置の前提: 配置後にスクリプトの実行権限が保たれていること
   （前提チェックで測る対象にする）。SetEnvIf の行の置き場所は Apache の
   実設定であり、README サンプルは設定ではないことの明記。
2. 層別の受け入れ条件: スクリプト単体 / 8445 直 / プロキシ経由ブラウザの
   3層それぞれに、ヘッダ無し → `(access denied)`、一致ヘッダ → 中身、
   の2ケースを固定する。
3. 文字コードの要件: 断片単体の応答にも charset が付くこと。置き場所は
   lib vhost の `AddDefaultCharset utf-8` が本筋。
