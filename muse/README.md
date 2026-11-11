# muse

Muse（muse-vm 上のエージェント）が日常の確認作業で使うシェルスクリプト置き場。
すべて読み取り専用で、状態を変更しない。

| スクリプト | 内容 |
|---|---|
| `muse-status.sh` | tailscaled の PID と開始時刻、API Bridge の `/health`、VM の稼働時間。tailscale CLI は呼ばない（この VM では CLI 呼び出しがデーモン再起動の副作用を持ちうるため） |
| `bridge-jobs.sh` | bridge-jobs キューの一覧。処理順（優先度降順、同点は作成順）で表示し、done 件数も出す |
| `pkg-versions.sh` | Nix プロファイルと .deb の導入済みパッケージを分けて表示。「最新」は引かない |
| `vm-info.sh` | CPU、メモリ、ディスク、OS の基本情報 |
| `procs.sh` | メモリ使用量の上位プロセス |
| `ports.sh` | 待ち受けポートの一覧 |
| `git-heads.sh` | ローカルの git リポジトリの状態（ブランチ、先頭、未コミット変更数、未 push 数。ネットワークには出ない） |
| `recent-jobs.sh` | bridge-jobs の直近の完了ジョブ |
| `graphs.sh` | プロセスのメモリ使用量、メモリ／スワップ、ディスクの棒グラフを HTML 断片で出力（SSI から直接呼ばれる前提で、完成した HTML を出す） |

前提: POSIX sh、python3（`bridge-jobs.sh` と `pkg-versions.sh` の JSON 読み取り用）、curl（`muse-status.sh` の health 確認用）。

`dashboard/` には、これらを Apache の SSI で呼び出すダッシュボードページがある（`dashboard/README.md` 参照）。

`samples/` には、muse-monitor が呼ぶ受信側のサンプル（`samples/receiver.py`）と、`bridge-jobs.sh`・`recent-jobs.sh` を試すキューの見本（`samples/bridge-jobs/`）がある。

仕様は `SPEC.md`。テストは `python3 -m unittest test/muse_scripts_test.py test/muse_samples_test.py`（リポジトリの直下で実行）。
