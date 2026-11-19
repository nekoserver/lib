# SPEC: lib/muse の読み取り用スクリプト

改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。2章に`hooks.sh`（2026-11-18に追加、表に無かった）を足し、表に無いスクリプトと、参照先の無いSPECを7章に記録した。5章の「確かめていないこと」のうち、ApacheでのSSIを本体のdemoコンテナで確かめた。要件の番号（`REQ-MS-…`）を7章に足した
評価: [`EVAL.scripts.opus-5.5.20261119.md`](EVAL.scripts.opus-5.5.20261119.md)
定期的な見直し: このSPECは[`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す

**対象**: `lib/muse/` の読み取り用スクリプト(下の表)・ダッシュボードの緑の区画・サンプル — Muse(muse-vm上のエージェント)とmuse-monitorが、muse-vmの状態を読み取るための部品。何を返すか、どこまでを保証するかを定める。

## 1. 原則

- **読み取り専用。** 状態を変えるコマンド(`rm`・`kill`・`systemctl`・`git push` など)を使わない。テスト(`test/muse_scripts_test.py`)が検査する。
- **tailscale CLIを呼ばない。** muse-vmでは、nix経由のCLI呼び出しがデーモンの再起動を起こしうる。状態は `ps`・`pgrep`・`curl` で確かめる。
- **ネットワークに出ない。** 外へ出るのは、loopback と unix ソケットだけ（`muse-status.sh` の `http://127.0.0.1:8080/health`、`tailnet-health.sh` の `http://127.0.0.1:8090/health`・`http://127.0.0.1:8080/health` と tailscaled の LocalAPI ソケット）。`git fetch` や「最新版」の取得はしない。
- **実行の経路を持たない。** 下の表のスクリプトは実行を伴わない。依頼の受付・承認・実行(`sdk-*`)は [`SPEC.md`](SPEC.md) が定める。muse-monitorも見るだけで、実行はしない。
- **POSIX sh と `set -u`。** 先頭は `#!/bin/sh`。`dash` で動くこと。
- **実行権限を持つ。** ダッシュボードのSSIが直接実行するので、gitで `100755` にする(テストが検査する)。

## 2. スクリプト

| スクリプト | 出力 | 終了コード | 読むもの |
|---|---|---|---|
| `muse-status.sh` | `== tailscaled ==`(PIDと開始時刻、または `not running`)、`== API Bridge ==`(`/health` の本文、または `(no response)`)、`== uptime ==` | 0 | `pgrep`・`ps`・`curl`・`/proc/uptime` |
| `bridge-jobs.sh [基点]` | `status` が `queued` のジョブを `prio <優先度>  <job_id>  <依頼の先頭80文字>` の形で、優先度の降順・同点は `created` の昇順に並べる。無ければ `queued: 0`。最後に `done: <件数>` | 0。キューが無いときは1(標準エラーに `queue not found`) | `<基点>/queue/*.json`・`<基点>/done/*.json`。基点の既定は `~/workspace/bridge-jobs` |
| `recent-jobs.sh [基点]` | `done/*.md` を新しい順に10件、`YYYY-MM-DD HH:MM  <見出し>`。見出しが無ければファイル名 | 0。置き場所が無いときは1 | `<基点>/done/*.md` |
| `pkg-versions.sh` | `== Nix profile ==`(ストアのパス名)と `== .deb (dpkg) ==`(導入数と主な版) | 0(主なパッケージが無くても0) | `~/.nix-profile/manifest.json`、無ければ `nix-env -q`。`dpkg-query` |
| `vm-info.sh` | CPU・メモリ・ディスク・OS | 0 | `nproc`・`/proc/cpuinfo`・`free`・`df`・`/etc/os-release` |
| `procs.sh` | `PID COMMAND RSS` と、メモリ上位10件(MiB) | 0 | `ps` |
| `ports.sh` | `tcp/udp <待ち受けアドレス>`。`ss` が無ければ `ss not found` | 0 | `ss -tuln` |
| `git-heads.sh` | `<HOMEからの相対パス> [<ブランチ>] <短いハッシュ> <件名> (dirty: <件数>, unpushed: <件数か?>)` | 0 | `~/muse-vm-hacks` と `~/workspace` の下(深さ3まで)の `.git` |
| `hooks.sh` | `hooks: <件数> 件`の後、`~/hooks/definitions/*.json`(バックアップ`*.before-*`を除く)ごとに`[<ID>] 有効/無効`・poll間隔・delivery・`script:`・`直近の実行:`・`直近の wake:`。定義の`prompt`は出さない。壊れた定義・ログ行は注記して続ける(2026-11-18、`7fb2b20`で追加。**README・ダッシュボードの断片・テストの対象にはまだ無い**。7章) | 0 | `~/hooks/definitions/*.json`・`~/hooks/logs/<id>.jsonl`(`python3`) |
| `graphs.sh` | 棒グラフのHTML断片(プロセスのメモリ、メモリ・スワップ、ディスク)。幅は0〜100% | 0 | `ps`・`free`・`df` |
| `tailnet-health.sh` | 環境変数 `MUSE_TAILNET_HEALTH_OK` が `1` でない場合は `(access denied)` の1行だけ（配信側が SetEnvIfExpr で正規ユーザーの場合にだけ立てるフラグ。REQ-TH-011）。`1` の場合は `== tailscaled ==`(PIDと開始時刻、または `not running`)、`== node ==`(LocalAPI から抽出した state・版・自身のIPv4・ホスト名・DNS名・online、取得できなければ `(local API unavailable)`)、`== receiver (:8090) ==` と `== API Bridge ==`(`/health` の本文、または `(no response)`)。仕様は SPEC.lib.tailnet-health.shtml | 0 | `pgrep`・`ps`・`curl`(LocalAPI の unix ソケット、`127.0.0.1:8090`、`127.0.0.1:8080`)・`python3`(応答の抽出) |

### bridge-jobs のジョブの形

`queue/*.json`・`done/*.json` は1件1ファイルのJSON。使う項目は `job_id`・`status`(`queued` だけが一覧に出る)・`priority`(無ければ0)・`created`(UNIX秒)・`request`(改行は空白にして表示)。読めないファイルは `(unreadable: <名前>: <理由>)` と表示して続ける。報告は `done/*.md` で、先頭の `#` 行を見出しにする。見本は `samples/bridge-jobs/`。

## 3. ダッシュボード(`dashboard/`)

- Apacheの SSI(`mod_include`)で、各断片(`*.shtml`)が `<!--#exec cmd="../<スクリプト>" -->` を実行する。作業ディレクトリは断片のあるディレクトリで、スクリプトは `../` で参照する。
- `graphs.sh` 以外の断片は、出力を `sed` でHTMLエスケープ(`&` `<` `>`)してから行末に `<br>` を付ける。`graphs.sh` は完成したHTMLを出し、ラベルから `&<>"` を除く。
- `index.shtml` の各区画は `data-frag` で断片を指し、「再実行」で断片を取り直す。全スクリプトに断片がある(テストが検査する)。
- Apache側の前提: `Options +Includes`(`IncludesNoExec` は不可)、スクリプトの実行権限、`HOME` がスクリプトの持ち主のホーム。公開範囲は置く側の設定で絞る。本体コンテナでは管理者だけが見る(本体ワーカーの管理者用の中継経由)。

## 4. 受信側のサンプル(`samples/receiver.py`)

muse-monitorが呼ぶ受信側(`docs/RECEIVER.md`、nekoserver/muse-monitor)の契約どおりのサンプル。

| 要求 | 応答 |
|---|---|
| `GET /health` | 200 `{"status": "ok"}`(認証なし。muse-monitorが相手を探すのに使う。2026-11-18の`7399ca0`から鍵の指紋は出さない) |
| `GET /monitor/<section>`・`GET /queue`、鍵が読めない | 503 `receiver_key_missing` |
| `Authorization: Bearer <鍵>` が無い・違う | 401 `{"error": "unauthorized"}`(比較はタイミングセーフ) |
| 未知の section、スクリプトが無い | 404 `unknown_section`(何も実行しない) |
| 正常 | 200 `{"section", "rc", "output", "truncated", "ts"}`。`output` は標準出力と標準エラー、64 KiBで切り詰め |
| 60秒を超えた | 504 `timeout`。子プロセスごと止める(プロセスグループで起動して `SIGKILL`) |
| `POST` など | 405 |

- 鍵は `~/.config/muse-receiver.env`(`--key-env-file`で変えられる)の `TS_API_KEY`(muse-monitorの `TS_API_KEY` と同じ値)だけから読む。最後の `TS_API_KEY=` 行が勝ち、前後の空白は除く。シェルの環境変数 `TS_API_KEY` は使わない。契約は muse-monitor の `docs/RECEIVER.md`(`SPEC.muse-monitor.security.hardening` の REQ-SEC-001/002/004/020)。
- 鍵の指紋は、2026-11-18の`7399ca0`(「鍵照合を稼働中実装(muse-vm)に統一」)から `/health`・401の本文に出さない。どちらの鍵が違うかは `receiver-check.sh` で確かめる。
- 扱う section は、スクリプトのある `status`・`jobs`・`pkgs`・`vm`・`procs`・`ports`・`git`・`recent`。muse-monitorの許可リストのうち、`diag`・`pending`・`execlog`・`sdk*` はスクリプトが無いので404。
- 既定で全アドレス(`0.0.0.0`)に待ち受ける。`127.0.0.1` では tailnet 経由の muse-monitor から接続拒否になる(2026-11-11 に起きた)。絞るときは `--host` に tailnet のアドレスを指定する。
- 鍵が読めなくても起動し、鍵の要る経路(`/monitor/*`・`/queue`)だけを503にする(鍵なしで通さない。起動時に `auth: unavailable` と出す)。2026-11-18より前の「鍵が無ければ起動しない」から変わった。

### 4.0 muse-vm での最善の状態(必ずこの状態にする)

muse-monitor が読めるのは、受信側が次の状態のときだけ。どれか1つでも外れると、muse-monitor は `receiver_not_found`(接続拒否)か `receiver_unauthorized` になる。

| 項目 | 最善の状態 | 外れたときの症状 |
|---|---|---|
| 起動のしかた | `samples/muse-receiver.service`(systemd のユーザー単位、`Restart=always`)で常駐。手で `python3 receiver.py` を起動したままにしない | 落ちても戻らない・再起動で消える |
| 待ち受け | 既定の `0.0.0.0:8090`。`--host 127.0.0.1` を付けない | muse-monitor から接続拒否 |
| 鍵 | `~/.config/muse-receiver.env` に `TS_API_KEY=<muse-monitor と同じ値>` の1行だけ。権限は600。`receiver.py` がこのファイルを直接読む。鍵はこのファイル以外(unit・スクリプト・コマンドの引数・シェルの環境変数)に書かない | 401 / 起動しない。値が漏れる |
| 鍵の名前 | `TS_API_KEY` だけ。別の名前を足さない | どの鍵が使われているか分からなくなる |
| 確認 | `sh samples/receiver-check.sh` が全部 OK(終了コード0) | — |

置き方:

```bash
mkdir -p ~/.config/systemd/user
cp ~/lib/muse/samples/muse-receiver.service ~/.config/systemd/user/
printf 'TS_API_KEY=%s\n' '<muse-monitorと同じ値>' > ~/.config/muse-receiver.env
chmod 600 ~/.config/muse-receiver.env
systemctl --user daemon-reload
systemctl --user enable --now muse-receiver
loginctl enable-linger "$USER"
sh ~/lib/muse/samples/receiver-check.sh
```

- `receiver-check.sh [ポート]` は読み取りだけで、鍵ファイルの有無と権限、待ち受けのアドレス(127.0.0.1 だけなら NG)、`/health`、鍵の一致(`/queue` が200か)を確かめる。鍵は表示せず、コマンドの引数にも出さない(`curl -K -` で渡す)。
- 受信側を変えたとき・`git pull` したとき・muse-vm を再起動したときは、`systemctl --user restart muse-receiver` のあと `receiver-check.sh` が全部 OK になるまで直す。
- muse-monitor 側からは `/health` の `node.receiverProbes` で同じことが見える(`ok` なら届いている)。

### 4.1 並行処理とキュー(muse-vmに負荷をかけないため)

muse-monitorの「全て取得」は15件を同時に送る。スクリプトを一斉に走らせないよう、次のように制御する。応答の形(契約)は変えない。

| 仕組み | 既定 | 内容 |
|---|---|---|
| 同時実行の上限 | `max_concurrent` 8 | 同時に動くスクリプトはこの数まで。既定の8項目をすべて同時に走らせられる |
| 待ち行列 | `max_queue` 32 | 上限を超えた要求は到着順に並ぶ(`threading.Condition` と待ち行列で、順番を保証する) |
| 待ち行列があふれたとき | — | 待たせずにすぐ503 `queue_full`(要求を際限なく溜めない) |
| 待ち時間 | `queue_wait` 30秒 | この時間内に順番が来なければ503 `busy` |
| 同じ section のまとめ | — | 実行中の section への要求は、その1回の結果を待って同じ結果を返す(同じスクリプトを重ねて走らせない) |
| 結果の使い回し | `cache_seconds` 5秒 | 成功(200)した結果だけを使い回す。失敗・時間切れは使い回さない |
| 古い結果の即答 | `stale_seconds` 300秒 | `cache_seconds` を過ぎても、この時間内の成功結果は待たせずに返し、裏で1回だけ取り直す。古さは応答の `ts` で分かる。待ち行列があふれているときは取り直さない |
| 起動時の準備 | — | 起動直後に全項目を並べて1回ずつ実行し、結果を用意する(最初の要求から待たせない) |
| 状態の確認 | `GET /queue`(鍵が必要) | `running`・`waiting`・`runningSections`・`maxConcurrent`・`maxQueue` |

- 待ち行列に数えるのは、実行を待っている要求だけ。同じ section の結果を待つ要求と、使い回しで返す要求は数えない。
- 想定外の例外が起きても、同じ section の結果を待つ要求を取り残さない(500 `receiver_error` を返す)。
- 起動時の指定: `--max-concurrent`・`--max-queue`。

### 4.2 項目の追加

- `--sections FILE` にJSON(`{"section": "スクリプト名"}`)を渡すと、既定の項目に足す(同じ名前なら置き換える)。コードを直さずに項目を増やせる。
- section の名前は英小文字で始まる32文字まで(英小文字・数字・`_`・`-`)。スクリプトは `lib/muse` の直下のファイル名に限り、`/`・`..` を含むものは起動時に拒否する。
- 足した項目をmuse-monitorから呼ばせるには、muse-monitorの許可リスト(6章)も合わせる。

## 5. テスト

```bash
python3 -m unittest test/muse_scripts_test.py test/muse_samples_test.py
```

- `test/muse_scripts_test.py`: 外部コマンドを `PATH` の先頭の偽物に差し替え、`dash` で各スクリプトの出力を確かめる。原則(1章)とダッシュボードの対応(3章)も検査する。
- `test/muse_samples_test.py`: 受信側のサンプルを空いているポートで実際に起動し、HTTPで4章の表を確かめる。並行処理とキュー(4.1、同時実行の上限・到着順・あふれ・待ち時間・まとめ・使い回し・`/queue`)と、項目の追加(4.2、不正な指定の拒否)も確かめる。bridge-jobsの見本を、実際のスクリプトで読めることも確かめる。
- **確かめていないこと**: muse-vmの実環境(Nix・tailscaled・API Bridge・実際のキュー)での実行。ApacheでのSSIは、2026-11-19に本体のdemoコンテナの内部Apache(8445)で確かめた(`index.shtml`は200、`tailnet.shtml`は正規ユーザーのフラグが無いので`(access denied)`)。

## 6. 変えるときの注意

- スクリプトを足したら、`README.md` の表・`dashboard/` の断片と `index.shtml` の区画・このSPECの2章を同時に直す(テストが漏れを落とす)。
- muse-monitorの受信側から呼ばせるなら、`samples/receiver.py` の `SECTIONS` と、muse-monitorの許可リスト(`src/do.ts`・`src/index.ts`・`docs/RECEIVER.md`)を合わせる。
- Museへの経路全体で決めておくべきことは、`SPEC.lib.20261111.muse-tailnet-lessons.md`(リポジトリの直下)。

## 7. 2026-11-19の現状と要件の番号(改訂で追記)

### 7.1 表と実物の食い違い

| 項目 | 内容 |
|---|---|
| `hooks.sh` | 2026-11-18の`7fb2b20`で追加された読み取り専用のスクリプト。6章の決まり(READMEの表・`dashboard/`の断片と`index.shtml`の区画・このSPECの2章を同時に直す)に沿っておらず、2章には今回の改訂で足した。READMEと断片は無いまま。テスト(`test/muse_scripts_test.py`)の`READ_ONLY_SCRIPTS`は固定の一覧で、`hooks.sh`を含まないため、漏れを落とせていない |
| `daemon-check.sh`・`exec-log.sh`・`pending.sh`・`diag.sh` | READMEにはあるが、2章の表にも`SPEC.md`の章にも、出力の形の定めが無い(`diag.sh`は`SPEC.md`の診断ゲートで名前だけ出る)。どちらのSPECが定めるかが決まっていない |
| 4章の受信側 | 2026-11-18の`7399ca0`で鍵の照合が変わったのに、4章が直されていなかった(`/health`の指紋、503のコード、401の本文、鍵が無いときの起動)。今回の改訂で実装に合わせた |
| `SPEC.lib.tailnet-health.shtml` | 2章の`tailnet-health.sh`の行とREADMEが「仕様は SPEC.lib.tailnet-health.shtml」とするが、libリポジトリに無い(muse-vmの側にあるとみられるが未確認)。`REQ-TH-011`もそこにある |
| テストの環境 | `GitHeadsTest`は`PATH`を`/usr/bin:/bin`に絞る。gitが`/usr/local/bin/git`にある環境(本体のdemoコンテナ)では、gitが見つからず出力が空になって落ちる。コードの不具合ではない |

### 7.2 要件の番号

| 番号 | 要件 | 本書の章 |
|---|---|---|
| REQ-MS-1 | 読み取り専用。状態を変えるコマンドを使わない | 1 |
| REQ-MS-2 | tailscale CLIを呼ばない。外へ出るのはloopbackとunixソケットだけ | 1 |
| REQ-MS-3 | POSIX shと`set -u`、`dash`で動く。シェバンのあるファイルはgitで`100755` | 1 |
| REQ-MS-4 | 各スクリプトの出力・終了コードは2章の表のとおり | 2 |
| REQ-MS-5 | ダッシュボードの断片はHTMLエスケープし、全スクリプトに断片がある | 3 |
| REQ-MS-6 | 受信側のサンプルは4章の表のとおり。鍵は`~/.config/muse-receiver.env`の`TS_API_KEY`だけ。既定で`0.0.0.0:8090` | 4・4.0 |
| REQ-MS-7 | 並行処理とキューは4.1の表のとおり | 4.1 |
| REQ-MS-8 | スクリプトを足したら、README・断片・本書の2章を同時に直す | 6 |

### 7.3 改訂の記録

| 日付 | モデル | 箇所 | 内容 | 根拠 |
|---|---|---|---|---|
| 2026-11-19 | opus-5.5 | 2章 | `hooks.sh`の行を追加 | `muse/hooks.sh`、`git show 7fb2b20` |
| 2026-11-19 | opus-5.5 | 4章 | `/health`の本文、鍵が無いときの503のコード、401の本文、鍵の読み方、鍵が無いときの起動を、`7399ca0`の後の実装に合わせた | `muse/samples/receiver.py`、`test/muse_samples_test.py`(通過)、muse-vmの`:8090/health`の実測(`{"status": "ok"}`) |
| 2026-11-19 | opus-5.5 | 5章 | ApacheでのSSIを確かめた旨に更新 | 8445の実測 |
| 2026-11-19 | opus-5.5 | 7章 | 食い違いと要件の番号を追加 | 7.1の表 |
