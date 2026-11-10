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

## Muse Code SDK 連携

Muse（本体）と Muse Code SDK（Python、`muse_code` パッケージ）に連動するもの。
SDK の実体は `.py` 側で、シェルは入口（解決・引数・タイムアウト）を担う。

| スクリプト | 内容 |
|---|---|
| `sdk-setup.sh` | SDK 用 venv（`~/.local/share/muse-sdk-venv`）を作り、本体と同版の `muse-code-sdk` を入れる。冪等 |
| `sdk-health.sh` | 本体と SDK の版、認証キーの有無（値自体は出さない）、serve デーモンの状態 |
| `sdk-ask.sh` | SDK で1ターンだけ指示を実行する。プロファイルは `-p`（既定 `:auto-review`、環境変数 `MUSE_PROFILE` でも指定可）。適用されなければ黙って落とさずエラー。`:unrestricted` は `MUSE_ALLOW_UNRESTRICTED=1` のときだけ。`-j` で結果サマリを JSON 出力 |
| `sdk-profiles.sh` | ホストの権限プロファイルとモデルを一覧（読み取り専用） |
| `sdk-sessions.sh` | ホストのセッション一覧と使用量（読み取り専用） |
| `sdk-serve.sh` | `muse serve --listen` のソケットデーモンを start / stop / status。ソケットは well-known の `~/.local/share/muse/session-server/session-server.sock`（この版は任意パス不可） |
| `sdk-common.sh` | 上記が読み込む共通の解決処理（単体では使わない） |

注意: ターンの実行にはホスト側の認証（サインイン、または serve プロセスから見える `META_API_KEY`）が要る。未認証だと構造化エラー `authRequired` が返る。`:auto-review` は自動レビュアーが使える状態（キー設定済み）でないと `profile_not_applied` になる。

`dashboard/` には、これらを Apache の SSI で呼び出すダッシュボードページがある（`dashboard/README.md` 参照）。
