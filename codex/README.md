# codex_promptを有効にする

**対象**: cf-containerの`/neko askgk codex_prompt="…"` — コンテナの初期設定の後に、必要なときだけ実行してCodexの応答を有効にする。

## 実行の順序

rootで実行する。どちらも何度実行してもよい。

```sh
# 1. 初期設定。Apacheの経路、worker、observer、ストリームのサーバーを戻す
~/lib/claude/ops/restore-claude-host.sh

# 2. Codexを使うときだけ
~/lib/codex/ops/enable-codex-prompt.sh
```

手順1だけでも、Claudeとネットワークは動く。そのとき`codex_prompt`は`codex_execution_failed`になる。手順1の前提は[`SETTINGS.claude-host.20261102.md`](../SETTINGS.claude-host.20261102.md)にある。

## 行うこと

1. `/opt/codex-web/bin/codex`から`/opt/node22/bin/codex`へリンクを張る。workerはこのパスのCodexを起動する。
2. `/var/lib/codex-web/.codex`（`codex-web`所有、0700）を作る。
3. `codex-web`にログインが無いときだけ、`/root/.codex/auth.json`をコピーする（`codex-web`所有、0600）。
4. `codex login status`の結果を表示する。

workerが起動していなければ、何も変えずに終了する。

## 認証

コピーした場合は、rootと`codex-web`で同じChatGPTのログインを共有する（2026-11-06にこの形を採用）。

- worker上のCodexは`--sandbox danger-full-access`で動くため、実行する処理からこの認証を読める。
- トークンの更新で、片方のログインが切れることがある。切れたら、その側で再度ログインする。
- `/root/.codex/auth.json`も無いときは、警告を出して先へ進む。`codex_prompt`は、ログインするまで`codex_execution_failed`のまま。

`codex-web`専用のログインにする場合は、`auth.json`を消してから次を実行する。

```sh
setpriv --reuid=codex-web --regid=codex-web --clear-groups --no-new-privs \
  env -i HOME=/var/lib/codex-web CODEX_HOME=/var/lib/codex-web/.codex PATH=/usr/local/bin:/usr/bin:/bin \
  /opt/codex-web/bin/codex login --device-auth
```

## 確認

`~/lib`で実行する。askgkは実際にCodexを呼ぶので、少額の利用が発生する。

```sh
python3 -m unittest discover -s codex/test -p '*_test.py'
ruby claude/test/manual/askgk_request.rb claude/api/tunnels.claude.rb 'codex_prompt="◯"'
```

askgkは`"via": "codex"`、`"ask_status": "done"`、`reply`を返す。

## ログイン時のネットワーク検査

このコンテナでは root の対話ログイン時に `ops/network-boot.sh` をバックグラウンドで実行する。結果は `/root/boot.log` に追記し、ファイアウォールの最新採取結果は `/root/firewall-login/` に保存する。手動で実行する場合は次のコマンドを使う。

```sh
/root/lib/codex/ops/network-boot.sh
/root/lib/codex/ops/network-boot.sh --prompt --panel
```

通常実行は既存のサービスを検査し、Codex の専用認証と app-server ソケットを確認する。内部 Apache は、現在の設定が既知の退避版と一致するときだけ復元する。初回のサービス配置には上記の `restore-claude-host.sh` を使う。署名付き検査は明示された ENV を優先し、未指定時は稼働中の配信プロセスの設定を参照する。

`--prompt` は Codex の実応答を検査する。`--panel` は公開パネルに1件投稿して返信を検査する。どちらも明示指定時だけ実行する。更新候補はログに記録し、パッケージの適用は行わない。
