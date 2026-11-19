# muse dashboard

`muse/` のスクリプト群を Apache の SSI（mod_include）で呼び出すダッシュボード。

色分け: 緑（バッジ「読み取り」）は読み取り専用で、ページ表示や再実行ボタンで
そのまま実行される。赤（バッジ「実行」）は実行系で、ページ表示では実行されず、
精査表示と確認チェックを経た手動送信でのみ動く。

サイドパネル（左端）で、読み取り区画の表示・非表示と、レイアウトのサンプル
（縦積み／2カラム／コンパクト）を切り替えられる。選択は Cookie
（`libdash_off`、`libdash_layout`）に保存され、表示は SSI の `#if` で
サーバ側が組み立てる。非表示にした区画は断片のスクリプトも実行されない。
配信側の Apache 設定（SetEnvIf と `SSILegacyExprParser On`）が前提で、
仕様は SPEC.lib.dashboard-state.shtml 版2（REQ-PN-001〜007）。

実行系は `ask.cgi`（実体は `../sdk-ask-cgi.py`）が受けるが、**受付のみで
実行はしない**。実行は、受ける側ホストでの承認があって初めて成立する
（承認ツールは `../sdk-approve.sh`、ホストのシェルでのみ操作できる）。
厳密な精査の仕掛け:

- 送信前に、承認後に実行されるコマンド・プロファイル・ワークスペース・
  指示の文字数と SHA-256 がページ上に表示され、確認チェックを入れるまで
  送信ボタンは無効
- プロファイルは許可リスト（`:read-only` / `:ask-me` / `:auto-review`）のみで、
  `:unrestricted` は選べない。ワークスペースはホーム配下の既存ディレクトリのみ。
  指示は8000文字まで
- 受付・承認・却下・実行はすべて監査ログ
  `~/.local/share/muse-sdk/exec-audit.jsonl` へ記録し（指示本文は残さず、
  SHA-256 と文字数）、`execlog.shtml` 区画で閲覧できる
- 承認待ちは `~/.local/share/muse-sdk/pending/<id>.json` に置かれ、
  ダッシュボードの「承認待ち」区画（緑・読み取り）でも見える

承認の直前には、防波堤として2つの関門が入る（どちらもホスト側）:

1. 整合性の再検証: 承認待ちファイルが登録後に書き換えられていても止める。
   プロファイルの許可リスト、ワークスペース（symlink 解決後にホーム配下か）、
   指示の SHA-256 が登録時と一致するか、長さ上限を再判定する
2. 診断ゲート: ダッシュボードと同じ `diag.sh` を走らせ、FAIL がある間は
   実行しない（WARN は記録して通す）。依頼は承認待ちのまま残る

悪用の想定と対策:

- 受付の洪水: 承認待ちの上限（既定20件、ホスト側の `MUSE_MAX_PENDING`）を
  超えた受付は拒否し、監査に残す
- 承認待ちファイルや監査ログの権限は 600、置き場所は 700
- 承認の経路はホストのシェルだけにあり、Web 側に承認 CGI は置かない。
  診断ゲートの無効化（`MUSE_DIAG_GATE=off`）や診断の差し替え
  （`MUSE_DIAG_CMD`）もホスト側の環境変数だけで、Apache の設定には
  絶対に入れないこと
- 実行コアの切り替え（`MUSE_ASK_IMPL=ts`）もホスト側の指定のみ

| ファイル | 内容 |
|---|---|
| `index.shtml` | ダッシュボード本体。各区画の「再実行」ボタンで断片を fetch し直し、その場でスクリプトを再実行して表示を更新する。「開く」は断片単体の表示（＝実行結果そのもの） |
| `graphs.shtml` | `../graphs.sh` の HTML 出力を埋め込む断片（グラフ表示） |
| `status.shtml` | `../muse-status.sh` の出力を埋め込む断片 |
| `tailnet.shtml` | `../tailnet-health.sh` の出力を埋め込む断片（ノードのヘルス） |
| `boot.shtml` | `../boot-state.sh` の HTML 出力を埋め込む断片（再起動と巻き戻り） |
| `cron.shtml` | `../cron-state.sh` の HTML 出力を埋め込む断片（定期実行の状態） |
| `hooks.shtml` | `../hooks.sh` の出力を埋め込む断片（フックの状態） |
| `jobs.shtml` | `../bridge-jobs.sh` の出力を埋め込む断片 |
| `pkgs.shtml` | `../pkg-versions.sh` の出力を埋め込む断片 |
| `vm.shtml` | `../vm-info.sh` の出力を埋め込む断片 |
| `procs.shtml` | `../procs.sh`（メモリ上位プロセス）の出力を埋め込む断片 |
| `ports.shtml` | `../ports.sh`（待ち受けポート）の出力を埋め込む断片 |
| `git.shtml` | `../git-heads.sh`（ローカル git リポジトリの状態）の出力を埋め込む断片 |
| `recent.shtml` | `../recent-jobs.sh`（直近の完了ジョブ）の出力を埋め込む断片 |

断片側で、出力を HTML エスケープしてから行末に `<br>` を付けている
（このリポジトリの `date.shtml` / `printenv.shtml` と同じ流儀）。

## Apache 側の前提

```apache
<Directory "/path/to/lib/muse/dashboard">
    Options +Includes +ExecCGI
    AddOutputFilter INCLUDES .shtml
    AddHandler cgi-script .cgi
</Directory>
```

- `ask.cgi` は実際に Muse Code を実行する入口なので、このディレクトリは
  必ず vhost 側の認証・許可リストで制限すること（公開厳禁）

tailnet 区画（`tailnet.shtml`）は、ノードの状態や自身の IP を出すため、
正規ユーザーにだけ表示する。ファイル単位の制限ではなく、Worker プロキシ
経路が認証済みユーザー名を載せる `X-Forwarded-User` ヘッダを照合して
フラグを立て、スクリプト側が動的に拒否する形にする
（仕様は SPEC.lib.tailnet-health.shtml の REQ-TH-011〜013）:

```apache
# REGULAR_USER はプレースホルダ。置く側が正規ユーザー名の実名に置き換える。
# 実名はこのリポジトリには書かない。置き換えない限りフラグは誰にも立たず、
# tailnet 区画は全員に (access denied) になる (fail-closed)。
SetEnvIf X-Forwarded-User ^REGULAR_USER$ MUSE_TAILNET_HEALTH_OK=1
```

このフラグは vhost 全体に立つため、同じフラグで `boot.shtml`（再起動と
巻き戻り）と `cron.shtml`（定期実行の状態）の区画も正規ユーザーにだけ
表示する（仕様は SPEC.lib.dashboard-state.shtml の REQ-DS-001）。

- この照合が効くのは、要求が Worker プロキシ経路を通り、`X-Forwarded-User`
  が Worker によって認証済みユーザー名で設定される場合だけである
  （ブラウザ由来の同名ヘッダは Worker が除去する）。ヘッダが無い経路では
  フラグは立たず、全員が拒否される

- `#exec` を使うため、`IncludesNoExec` は付けないこと
- `#exec cmd` の作業ディレクトリは断片ファイルのあるディレクトリになる前提で、
  スクリプトは相対パス `../` で参照している
- スクリプト側に実行権限（`+x`）と、Apache の実行ユーザからの読み取り権限が要る
- `bridge-jobs.sh` と `pkg-versions.sh` は `$HOME` 配下
  （`~/workspace/bridge-jobs`、`~/bin/nix-env`、`~/.nix-profile`）を見るため、
  Apache の実行環境の `HOME` がスクリプトの持ち主のホームを指していること

注意: このダッシュボードはスクリプトの素の出力をそのまま表示する。
公開範囲は置く側の vhost / 認証設定で制限すること。
