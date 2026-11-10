# muse dashboard

`muse/` のスクリプト群を Apache の SSI（mod_include）で呼び出すダッシュボード。

| ファイル | 内容 |
|---|---|
| `index.shtml` | ダッシュボード本体。60秒で自動再読み込み |
| `status.shtml` | `../muse-status.sh` の出力を埋め込む断片 |
| `jobs.shtml` | `../bridge-jobs.sh` の出力を埋め込む断片 |
| `pkgs.shtml` | `../pkg-versions.sh` の出力を埋め込む断片 |
| `vm.shtml` | `../vm-info.sh` の出力を埋め込む断片 |

断片側で、出力を HTML エスケープしてから行末に `<br>` を付けている
（このリポジトリの `date.shtml` / `printenv.shtml` と同じ流儀）。

## Apache 側の前提

```apache
<Directory "/path/to/lib/muse/dashboard">
    Options +Includes
    AddOutputFilter INCLUDES .shtml
</Directory>
```

- `#exec` を使うため、`IncludesNoExec` は付けないこと
- `#exec cmd` の作業ディレクトリは断片ファイルのあるディレクトリになる前提で、
  スクリプトは相対パス `../` で参照している
- スクリプト側に実行権限（`+x`）と、Apache の実行ユーザからの読み取り権限が要る
- `bridge-jobs.sh` と `pkg-versions.sh` は `$HOME` 配下
  （`~/workspace/bridge-jobs`、`~/bin/nix-env`、`~/.nix-profile`）を見るため、
  Apache の実行環境の `HOME` がスクリプトの持ち主のホームを指していること

注意: このダッシュボードはスクリプトの素の出力をそのまま表示する。
公開範囲は置く側の vhost / 認証設定で制限すること。
