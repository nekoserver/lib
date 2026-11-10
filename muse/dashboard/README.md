# muse dashboard

`muse/` のスクリプト群を Apache の SSI（mod_include）で呼び出すダッシュボード。

色分け: 緑（バッジ「読み取り」）は読み取り専用で、ページ表示や再実行ボタンで
そのまま実行される。赤（バッジ「実行」）は実行系で、ページ表示では実行されず、
精査表示と確認チェックを経た手動送信でのみ動く。

実行系は `ask.cgi`（実体は `../sdk-ask-cgi.py`）が受ける。厳密な精査の仕掛け:

- 送信前に、実行されるコマンド・プロファイル・ワークスペース・指示の文字数と
  SHA-256 がページ上に表示され、確認チェックを入れるまで実行ボタンは無効
- プロファイルは許可リスト（`:read-only` / `:ask-me` / `:auto-review`）のみで、
  `:unrestricted` は選べない。ワークスペースはホーム配下の既存ディレクトリのみ。
  指示は8000文字まで
- 結果は要約せず JSON 全文と本文を表示する
- 実行のたびに監査ログ `~/.local/share/muse-sdk/exec-audit.jsonl` へ記録し
  （指示本文は残さず、SHA-256 と文字数）、`execlog.shtml` 区画で閲覧できる

| ファイル | 内容 |
|---|---|
| `index.shtml` | ダッシュボード本体。各区画の「再実行」ボタンで断片を fetch し直し、その場でスクリプトを再実行して表示を更新する。「開く」は断片単体の表示（＝実行結果そのもの） |
| `graphs.shtml` | `../graphs.sh` の HTML 出力を埋め込む断片（グラフ表示） |
| `status.shtml` | `../muse-status.sh` の出力を埋め込む断片 |
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

- `#exec` を使うため、`IncludesNoExec` は付けないこと
- `#exec cmd` の作業ディレクトリは断片ファイルのあるディレクトリになる前提で、
  スクリプトは相対パス `../` で参照している
- スクリプト側に実行権限（`+x`）と、Apache の実行ユーザからの読み取り権限が要る
- `bridge-jobs.sh` と `pkg-versions.sh` は `$HOME` 配下
  （`~/workspace/bridge-jobs`、`~/bin/nix-env`、`~/.nix-profile`）を見るため、
  Apache の実行環境の `HOME` がスクリプトの持ち主のホームを指していること

注意: このダッシュボードはスクリプトの素の出力をそのまま表示する。
公開範囲は置く側の vhost / 認証設定で制限すること。
