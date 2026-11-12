# Muse への伝達事項

Muse(muse-vm 上のエージェント)に知らせることを、更新のたびにここへ書き足す。新しい日付の節を先頭に置き、同じ日は1つの節にまとめる。各節には「やること」を必ず書く。

Muse は作業を始める前に、前回読んだ日付より新しい節を読み、「やること」を済ませる。済ませた結果(`receiver-check.sh` の OK/NG の行など)は報告に貼る。

## 2026-11-13

### 変わったこと

- **本体(Claude Code・Codex)から Muse への修復依頼を、決まった形で送るようにした。** 送り方・本文の形は本体 SPEC `SPEC.cloudflare-workers-github-oauth-1.20261113.muse-repair-protocol.md`。依頼は本体の非同期ジョブ(`/agent-jobs`、送り手 `agent: "claude"` または `"codex"`)で届く。
- **api-bridge(muse-vm-hacks の `files/api-bridge/server.py`)を 0.4.1 にした**(PR #1、885a661d)。呼び出し側が接続を切ったら、ジョブを inbox から取り下げて `JOB_LOCK` をすぐ放す。これまでは600秒ロックを握ったまま待ち、捨てられたジョブで起こされ、後続の要求も詰まっていた。

### やること

- **依頼には、どの場合も必ず返信を書く。** 実施した・一部だけ・断る・保留のどれでも、outbox に返信を書く。黙ると api-bridge は600秒待って 504 を返し、送った側には理由が残らない(2026-11-13 に2件続けてそうなった)。
- **返信の先頭行は `結果: 実施` / `結果: 一部` / `結果: 断る` / `結果: 保留` のどれかにする**(語は候補。合わない語があれば、返信で言い換えを伝える)。2行目以降に、依頼の「返信に書くこと」への答えを書く。断る・保留のときは理由を1行書く。
- **再起動を伴う依頼は、返信を書いたあとで再起動する**(先に再起動すると、返信を運ぶ api-bridge が止まる)。
- api-bridge 0.4.1 を入れる: `~/muse-vm-hacks` を main に更新し、`files/api-bridge` で `~/bin/nix-env -f api-bridge.nix -i`、返信のあとで `files/scripts/bootstrap-api-bridge.sh` で再起動する。入った版(`/nix/packages` の `muse-api-bridge`)を報告に貼る。

## 2026-11-12

### 変わったこと

- **cf-container から muse-vm へ tailnet で届かなかった原因が分かり、回避した。**
  - muse-vm の tailscaled は直接の外向き通信が制限されていて(`tailscale netcheck` で `UDP: false`、どの DERP にも応答なし)、今つながっている DERP 以外へは新しく接続できない。cf-container の home DERP が syd だったため、muse-vm からの WireGuard の返事が届かず、ハンドシェイクが一度も成立しなかった(鍵・ACL は原因ではなかった。nodekey・discokey は両方向で一致)。
  - 回避: tailnet のポリシーに `"derpMap": {"Regions": {"5": null}}` を足し、syd を使わないようにした。cf-container は tok に移り、ハンドシェイクが成立、`/neko askgk muse_prompt=…` が `done` になった(2026-11-12 02:50 UTC、約41秒)。
  - 根本の対処(未実施): muse-vm の外側のファイアウォールで、tailscaled の直接の外向き通信を `derp*.tailscale.com` の 443/tcp と 3478/udp に許可する。そうすれば derpMap の制限は外せる。
- **本体 AIチャットの Muse の「直送」は、コンテナを通さない経路に戻る**(本体 nekoserver/cloudflare-workers-github-oauth-1#2574)。
  - 直送 = 本体 Worker 内の Tailscale WASM ノード `main-worker-muse` → muse-vm:8080。接頭語なしの Muse と `/askmuse` はこれが既定。demo コンテナ(`server.js`)を通るのは、AIチャットの ⚙ で旧コンテナ直通を選んだときだけ。
  - 直前の本体(#2572)は直送を demo コンテナ経由に固定していて、AIチャットに「Muse がタイムアウトしました(300秒)」が出ていた。muse-vm と鍵は正常だった。
  - `main-worker-muse` は送る前に、自分が `Running` になり muse-vm がオンラインに見えるまで最大20秒待つ。
  - Muse へ届く経路の一覧(7系統、コンテナの要否・鍵)は本体 SPEC `SPEC.cloudflare-workers-github-oauth-1.20261112.muse-request-routes.md` の7章。経路の名前と muse-vm 側の鍵の名前は、まだ決めていない。
- **lib の worker は、Muse にプロンプトを送る前に `GET /v1/models`(`MUSE_API_KEY` を付ける)で到達を確かめる。** 10秒以内に HTTP の応答(状態は問わない)が無ければ、すぐ `muse_connection_failed` を返す。これまでは127秒待って Cloudflare の 524 になり、Slack に理由が届かなかった。
- **AIチャットからの Muse の要求に返事が来ない(2026-11-12 06:40 UTC 以降)。** muse-vm に届く(通知が来る)のに、送信のちょうど10分後に毎回同じ283バイトの短い応答が返り、本体は300秒でタイムアウトしている。本体の Worker 内 WASM 経由でも、コンテナ経由でも同じだった。どこで止まるかを確定するため、api-bridge を tailnet を通さずに直接試すテスト `test/muse_direct_live_test.py` を足した(本体と同じ形の要求を送り、`/health`・`/ping`・短い推論(stream 無し・`stream:false`)の4段階で、どこで止まるかを1行ずつ出す)。

### やること

- tailscaled にプロキシを渡さない今の起動のしかたは変えない(渡すと今つながっている DERP の接続を壊す恐れがある)。
- muse-vm の tailscaled を再起動したら、`tailscale ping 100.107.14.122`(cf-demo-container)が通ることを確かめ、結果を報告に貼る。通らなければ `tailscale netcheck` の結果も貼る。
- 本体の直送(`main-worker-muse` から)で「Museへの接続を確認できません」が続くと知らされたら、`tailscale ping main-worker-muse` の結果を報告に貼る(上の DERP の制限で、`main-worker-muse` の home DERP に届かない可能性がある)。
- muse-vm の上で、tailnet を通さずに api-bridge を直接試し、出力の `health:`・`ping:`・`inference(stream無し):`・`inference(stream:false):` の4行と、失敗したテストの文をそのまま報告に貼る(鍵の値は貼らない)。
  `cd ~/lib && git pull && MUSE_LIVE_URL=http://127.0.0.1:8080 MUSE_API_KEY=<api-bridge の鍵> python3 -m unittest test/muse_direct_live_test.py -v`
- `/ping` は返るのに推論が返らないときは、api-bridge のログで、日本時間 2026-11-12 15:40・16:22・17:20 ごろに受け取った要求がどう終わったか(10分後に何を返したか)も貼る。

## 2026-11-11

### 変わったこと

- **受信側(`muse/samples/receiver.py`)の最善の状態を決めた**(`muse/SPEC.scripts.md` の 4.0)。
  - 常駐は `muse/samples/muse-receiver.service`(systemd のユーザー単位、落ちても5秒で戻る)。手で `python3 receiver.py` を起動したままにしない。
  - 待ち受けは既定の `0.0.0.0:8090`。`--host 127.0.0.1` を付けない(muse-monitor から接続拒否になる。今日これで `receiver_not_found` が出た)。
  - 鍵は `~/.config/muse-receiver.env`(権限600)の `TS_API_KEY=<muse-monitor と同じ値>` の1行だけ。
- **`receiver.py` は鍵を `~/.config/muse-receiver.env` だけから読む。** シェルの環境変数 `TS_API_KEY` は使わない(食い違えば起動時に名前だけ表示する)。ファイルに鍵が無ければ起動しない。
- **鍵の指紋**(sha256 の先頭8桁)を、起動時・`/health`・401 の本文に出す。muse-monitor が `receiver_unauthorized` を返したら、本文の `receiver.expectedKeyFingerprint`(受信側)と `presentedKeyFingerprint`(muse-monitor)を見比べる。違えば `~/.config/muse-receiver.env` の値が違う。
- **`receiver.py` の待ち時間を減らした。** 300秒以内の成功結果はすぐ返して裏で取り直す。起動直後に全項目を1回ずつ実行する。同時実行は8本まで。
- **`muse/` の直接実行されるスクリプトに実行権限を付けた**(`pending.sh` が `sdk-approve.sh: Permission denied` で止まっていた)。`#!` を持つファイルはすべて 100755 で、テストが検査する。
- **muse-monitor は、受信側が答えないとき5秒(2.5秒おきに2回)探し直してから `receiver_not_found` を返す。** それでも拒否なら、受信側は止まったまま。
- **本体から「コンテナの版の一覧」が要望として届く**(`/muse-wasm-test` の「コンテナの版の一覧をMuseに渡す」)。届いたら一覧を `~/workspace/container-versions.md` に上書き保存する。コンテナやパッケージそのものは変えない。返信は保存先と「更新あり」の件数・パッケージ名だけ。
- **脆弱性チェックで見つかった Muse のコード**: `muse-vm-hacks/files/api-bridge/server.py:1108` の `sess.secret == secret` が通常の比較になっている。
- **vuln-watch 第2回**(2026-11-11):
  - Node.js 26.13.1 に上げる PR を出した(musevm・redmine)。本体と dynamicneko はイメージの作り直しが要るため未対応。
  - Git の脆弱性(CVE-2026-111760 ほか6件)はディストリの修正が未出荷。それまで、信頼できないリポジトリの clone(特に `--recurse-submodules`)やタグのマージをしない。
  - APT の CVE-2026-109518 は修正版あり。muse-vm で `sudo apt-get -o Acquire::Retries=0 update && sudo apt-get -o Acquire::Retries=0 install --only-upgrade apt` を、ほかの更新より先に実行する。
  - `lib/claude/ops/bridge_jobs.py` の claim トークンの比較を `hmac.compare_digest` にした(lib の PR)。
- 決まり(`CLAUDE.md`): 変数・シークレット・設定スイッチを承認なしに増やさない。同じ値を別名に分けない。テストファーストを徹底する。受信側に触れたら `receiver-check.sh` が全部 OK になるまで終えない。

### やること

1. `cd ~/lib && git pull`(実行権限の変更も入る)。
2. `~/.config/muse-receiver.env` に `TS_API_KEY=<muse-monitor と同じ値>` を書き、`chmod 600`。
3. `muse/SPEC.scripts.md` 4.0 の「置き方」で `muse-receiver.service` を入れ、`systemctl --user enable --now muse-receiver` と `loginctl enable-linger "$USER"`。手で起動した `receiver.py` が残っていれば止める。
4. `sh ~/lib/muse/samples/receiver-check.sh` が全部 OK になるまで直し、OK/NG の行を報告に貼る。
5. `sh ~/lib/muse/pending.sh` が `Permission denied` なしで動くことを確かめる。
6. `muse-vm-hacks/files/api-bridge/server.py` の秘密の比較を `hmac.compare_digest` に替える(テストを先に書く)。
7. muse-vm の apt を先に更新する(上の手順)。結果の版(`apt --version`)を報告に貼る。
8. 修正が出るまで、信頼できないリポジトリを `--recurse-submodules` で clone しない。
