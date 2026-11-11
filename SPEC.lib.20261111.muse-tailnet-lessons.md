# SPEC 2026-11-11: Museへの経路(tailnet)で本来決めておくべきだったこと

**対象**: Worker からMuse(muse-vm)へ届く経路 — 本体ワーカー(`nekoserver/cloudflare-workers-github-oauth-1`)、muse-monitor(`nekoserver/muse-monitor`)、muse-vmの受信側(`:8090` の `/monitor/<section>`、`:8080` のMuse API)。2026-11-10〜11に起きた失敗から、最初のSPECに書いておくべきだったことをまとめる。次に同じ種類の経路を作るときは、実装の前にこの5項目を決める。

## 背景(何が起きたか)

- muse-monitorは、デプロイ後すべての要求が失敗していた。原因はnetmapの読み違いで、WASMは `peers[].name`・`addresses` を出すのに、コードは `TailscaleIPs`・`Addresses` を読んでいた。muse-vmが見つからず、必ず `receiver_not_found` になっていた(nekoserver/muse-monitor#7 で修正)。
- そのほかに次の問題があった。
  - 同時に来た要求がそれぞれノードを作っていた。
  - Runningでないノードがそのまま使われていた。
  - 鍵(`TS_AUTHKEY`・`TS_API_KEY`)の取り違えで、意味の無いエラーが出ていた。
  - 本体の `MuseAgentJobs` は、失敗の理由を捨てていた(`queued → sending → failed` だけが見えた)。
  - `/muse-wasm-test` はブラウザ自身をノードにしていて、開くたびにTailscaleへのログインが要った。
- テストは偽物のWASMで合格していたが、実経路(Worker → ノード → tailnet → muse-vm)は一度も通していなかった。

## 決めておくべきだったこと

### 1. tailnetへの出口(Tailscaleのノード)は1つにする

- 今は3か所で別々にノードを立てている。本体のDO `TailscaleWasm`(`main-worker-muse`)、muse-monitorのDO `MonitorGateway`(`muse-monitor`)、以前の `/muse-wasm-test` のブラウザ(`muse-wasm-test`)。同じ種類の不具合(netmapの読み方、ログイン、鍵、状態の保存)が、それぞれ別々に出た。
- 出口は1つのノードにまとめ、ほかのWorkerはそこを経由する(Service Bindingなど)。
- ノードの状態は、そのノードを持つDurable Objectに保存する。秘密鍵が入るので、ブラウザには置かない。
- ログインは認証キーで自動で行う。人が毎回承認する作りにしない。
- **未決定**: muse-monitorのノードを本体のノードに寄せるかどうか。設計の変更なので、ユーザーの判断を待つ。

### 2. 外部パッケージの出力の形を、仕様として固定する

- `@ai-ecoverse/wasm-tailscale`(1.104.1-13)のnetmapは `self`・`peers`・`name`・`addresses`。`status()` は `state`・`peers`・`name`・`dnsName`・`online`。
- 形は推測で書かず、実物(main.wasmのjsonタグや実際の出力)で確かめてからテストに書く(契約テスト)。そうすれば、読み違いは書いた時点でテストが落とす。
- パッケージの版を上げるときは、先にこの契約テストを確かめ直す。

### 3. 鍵は用途ごとに1つにし、名前と役割を表にする

| 用途 | 例 |
|---|---|
| ノードがtailnetに参加する | `TS_AUTHKEY`(muse-monitor)、`TAILSCALE_WASM_AUTHKEY`(本体) |
| Workerが受信側(muse-vm)を呼ぶ | `TS_API_KEY` = 受信側の `MUSE_CODE_WASM_API_KEY`、`MUSE_API_KEY`(本体 → Muse API) |
| 呼び出し元がWorkerを呼ぶ | `WORKER_API_KEY`、`MONITOR_HMAC_SECRET`(本体 → muse-monitor) |

- フォールバック(片方が無ければもう片方を使う)を入れるなら、SPECに書く。
- どの鍵が使われたかを、値は出さずに状態のAPIで見えるようにする(muse-monitorの `authKeySource`・`keySource`)。

### 4. 失敗には必ず理由を返す

- `unauthorized` だけ、`failed` だけ、という応答は禁止する。どこで何が拒否したかが分かるコードにする。例: `receiver_unauthorized`(受信側が鍵を拒否)、`receiver_key_not_configured`、`receiver_not_found`、`tailnet_unavailable`、`HTTP 503 tailscale_not_connected`。
- 送り直してよい失敗(まだ相手に何も届いていない)と、送り直してはいけない失敗(届いたかどうか分からない)を区別し、SPECに書く。

### 5. 完成の条件に、実経路の確認を入れる

- 偽物を使ったテストの合格だけで「できた」としない。
- 受け入れ条件として、運用者のキーで Worker → ノード → tailnet → muse-vm を1回通す。手順は `/api/status`(ノードの状態・鍵の出どころ・muse-vmの候補)→ 実際の項目の取得。
- 実経路をまだ通していないときは、報告に「未確認」と書く。

## 関連

- nekoserver/muse-monitor#7(netmapの読み違い、ノードの二重作成、Runningの待ち方、鍵のフォールバック、受信側の認証エラーの説明)
- nekoserver/cloudflare-workers-github-oauth-1 の #2556(本体 → muse-monitor)、#2557(`MuseAgentJobs` の失敗理由と再試行、`/muse-wasm-test` のログインをWorkerのノードに任せる)
- 本体の `NOTICE.cloudflare-workers-github-oauth-1.20261110.md`(ノードの所在、`bridge_jobs` と `MuseAgentJobs` の違い)
