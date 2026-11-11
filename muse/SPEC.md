# SPEC: lib/muse

**対象**: `lib/muse/` のスクリプト・ダッシュボード・サンプル — Muse(muse-vm上のエージェント)とmuse-monitorが、muse-vmの状態を読み取るための部品。何を返すか、どこまでを保証するかを定める。

## 1. 原則

- **読み取り専用。** 状態を変えるコマンド(`rm`・`kill`・`systemctl`・`git push` など)を使わない。テスト(`test/muse_scripts_test.py`)が検査する。
- **tailscale CLIを呼ばない。** muse-vmでは、nix経由のCLI呼び出しがデーモンの再起動を起こしうる。状態は `ps`・`pgrep`・`curl` で確かめる。
- **ネットワークに出ない。** 外へ出るのは、`muse-status.sh` の `http://127.0.0.1:8080/health`(API Bridge)だけ。`git fetch` や「最新版」の取得はしない。
- **実行の経路を持たない。** 依頼の受付・承認・実行は、このディレクトリの外(ホストのシェル)で行う。muse-monitorも見るだけで、実行はしない。
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
| `graphs.sh` | 棒グラフのHTML断片(プロセスのメモリ、メモリ・スワップ、ディスク)。幅は0〜100% | 0 | `ps`・`free`・`df` |

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
| `GET /health` | 200 `{"status": "ok"}`(muse-monitorが相手を探すのに使う) |
| 未知の section、スクリプトが無い | 404 `unknown_section`(何も実行しない) |
| 正常 | 200 `{"section", "rc", "output", "truncated", "ts"}`。`output` は標準出力と標準エラー、64 KiBで切り詰め |
| 60秒を超えた | 504 `timeout`。子プロセスごと止める(プロセスグループで起動して `SIGKILL`) |
| `POST` など | 405 |

- 鍵の照合はしない。環境変数も読まない。`Authorization` ヘッダーは見ない。tailnetの中(muse-monitor)からだけ呼ばれる前提で、公開範囲は `--host` で絞る。
- 扱う section は、スクリプトのある `status`・`jobs`・`pkgs`・`vm`・`procs`・`ports`・`git`・`recent`。muse-monitorの許可リストのうち、`diag`・`pending`・`execlog`・`sdk*` はスクリプトが無いので404。
- 既定で `127.0.0.1` にだけ待ち受ける。tailnetに出すときは `--host` で明示する。

### 4.1 並行処理とキュー(muse-vmに負荷をかけないため)

muse-monitorの「全て取得」は15件を同時に送る。スクリプトを一斉に走らせないよう、次のように制御する。応答の形(契約)は変えない。

| 仕組み | 既定 | 内容 |
|---|---|---|
| 同時実行の上限 | `max_concurrent` 4 | 同時に動くスクリプトはこの数まで |
| 待ち行列 | `max_queue` 32 | 上限を超えた要求は到着順に並ぶ(`threading.Condition` と待ち行列で、順番を保証する) |
| 待ち行列があふれたとき | — | 待たせずにすぐ503 `queue_full`(要求を際限なく溜めない) |
| 待ち時間 | `queue_wait` 30秒 | この時間内に順番が来なければ503 `busy` |
| 同じ section のまとめ | — | 実行中の section への要求は、その1回の結果を待って同じ結果を返す(同じスクリプトを重ねて走らせない) |
| 結果の使い回し | `cache_seconds` 5秒 | 成功(200)した結果だけを使い回す。失敗・時間切れは使い回さない |
| 状態の確認 | `GET /queue` | `running`・`waiting`・`runningSections`・`maxConcurrent`・`maxQueue` |

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
- **確かめていないこと**: muse-vmの実環境(Nix・tailscaled・API Bridge・実際のキュー)での実行と、Apacheに置いたときのSSIの動作。

## 6. 変えるときの注意

- スクリプトを足したら、`README.md` の表・`dashboard/` の断片と `index.shtml` の区画・このSPECの2章を同時に直す(テストが漏れを落とす)。
- muse-monitorの受信側から呼ばせるなら、`samples/receiver.py` の `SECTIONS` と、muse-monitorの許可リスト(`src/do.ts`・`src/index.ts`・`docs/RECEIVER.md`)を合わせる。
- Museへの経路全体で決めておくべきことは、`SPEC.lib.20261111.muse-tailnet-lessons.md`(リポジトリの直下)。
