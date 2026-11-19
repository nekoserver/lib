# SPEC: restore-claude-host.sh の変更履歴とカバー範囲（2026-11-18）

作成日: 2026-11-18（UTC）
作成: opus-5.5（Claude Opus 5.5、Claude Code）
対象: [`claude/ops/restore-claude-host.sh`](ops/restore-claude-host.sh)（`main`の`14e82cb`時点）
状態: 現状の記録。スクリプト・設定は変えていない。
改訂: 2026-11-19、opus-5.5（Claude Opus 5.5、Claude Code）。2章に#12（PR #161、フックをユーザーの設定へ）を足し、4章の「コンテナの作り直しの直後」を起動時のログで確かめ直した。要件の番号（`REQ-RCH-…`）を5章に足した
評価: [`EVAL.claude.20261118.restore-claude-host.opus-5.5.20261119.md`](EVAL.claude.20261118.restore-claude-host.opus-5.5.20261119.md)
定期的な見直し: このSPECは[`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順で、定期的に実情に合わせて改訂し、評価し直す

関連: [`SPEC.claude.20261102.md`](SPEC.claude.20261102.md)（別名版の全体と、復元の最初の形）、[`../SPEC.lib.20261118.opus-5.5.md`](../SPEC.lib.20261118.opus-5.5.md)の4章（復元の要件`REQ-RST-…`）、[`../EVAL.lib.20261118.opus-5.5.md`](../EVAL.lib.20261118.opus-5.5.md)（同日の実行結果）、[`../SETTINGS.claude-host.20261102.md`](../SETTINGS.claude-host.20261102.md)（手順）。

---

## 1. 誰が、いつ作ったか

**対象**: スクリプトの作成者 — 何を根拠にそう言えるか。

| 項目 | 内容 | 根拠 |
|---|---|---|
| 作成 | 2026-11-02 05:08 UTC、コミット[`f0493d5`](https://github.com/nekoserver/lib/commit/f0493d58e110f5508ab972d86352d154eaae65dd)（[PR #103](https://github.com/nekoserver/lib/pull/103)） | `git log --follow`の最古のコミットが`A claude/ops/restore-claude-host.sh`（名前の変更は無い） |
| エージェント | **Claude Opus 5.5**（Claude Code）。作成から最新までの11コミットすべて | 各コミットの`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`の行 |
| gitの作者・コミッター | `neko`（11コミットすべて） | `git log --format='%an %cn'` |
| 他のエージェント | 無い（Codexなど、別のエージェントの行が付いたコミットは無い） | 同上 |

エージェント名は、コミットの`Co-Authored-By`の行だけを根拠にしている。どの会話（セッション）で作られたかは、gitからは分からない。

---

## 2. 変更の履歴（新しい順）

**対象**: `claude/ops/restore-claude-host.sh`を変えた11コミット — それぞれ何が起きていて、どこまでをカバーするようになったか。

日時はコミットの作成日時（UTC）。PRのマージは、日本時間で同日か翌日。「行数」はこのスクリプトだけの増減。

| # | 日時（UTC） | コミット | PR | エージェント | 行数 | 起きていたこと | 追加でカバーしたこと |
|---|---|---|---|---|---|---|---|
| 12 | 2026-11-19 00:27 | [`2add69a`](https://github.com/nekoserver/lib/commit/2add69a0d1d90d0dc851f3db9ad1f0fc34e0584e) | [#161](https://github.com/nekoserver/lib/pull/161) | Claude Opus 5.5 | +3/−1（本体は`restore-claude-hooks.sh`） | `/root`で始めたClaude Codeのセッションでは本体のフックが1つも効かず、全体テストが止まらなかった。復元は`hooks: OK`と出ていた | **どのディレクトリでも働くガードを`~/.claude/settings.json`へ書き、全体テストのガードが実際に止めることを確かめる**（[`SPEC.claude.20261119.restore-claude-hooks.md`](SPEC.claude.20261119.restore-claude-hooks.md)） |
| 11 | 2026-11-18 21:55 | [`b583c2a`](https://github.com/nekoserver/lib/commit/b583c2a96fc8e497763808d84d53687e86ca8236) | [#156](https://github.com/nekoserver/lib/pull/156) | Claude Opus 5.5 | +13/−7 | 本体のentrypointが`/root/lib`を`/var/www/html/lib`へbind mountしてから復元を呼ぶようになり（本体`lib-restore-wait.sh`、2026-11-18）、`cp -a`が「are the same file」で失敗、`set -e`で復元が止まっていた | **bind mountのときは複製を飛ばす**（`[ "$LIB" -ef "$WWW" ]`） |
| 10 | 2026-11-18 21:50 | [`ba65005`](https://github.com/nekoserver/lib/commit/ba65005e5fa95904cf889915daa96074e854aef3) | [#155](https://github.com/nekoserver/lib/pull/155) | Claude Opus 5.5 | +17/−0 | イメージの内部Apache（`010-lib.conf`、8445）に会話ストリームの中継が無く、tree-viewのワーカータブが真っ白（`/lib/api/chat/session`が404） | **8445に中継が無ければ`apache-lib-internal-chat.conf`をIncludeする**。既にあれば何もしない、`010-lib.conf`が無ければ飛ばす（本体PR #2660がイメージに入るまでのつなぎ） |
| 9 | 2026-11-14 21:59 | [`6b33eb7`](https://github.com/nekoserver/lib/commit/6b33eb707ffc7d4cff89eaeacf9d16d246a1b673) | [#149](https://github.com/nekoserver/lib/pull/149) | Claude Opus 5.5 | +3/−3 | イメージの`/lib/api/tunnels`の別名が`lib-askgk-api.conf`のIncludeの中へ移り、イメージの`askgk.cgi`が先に一致してトークンが渡らなかった | **`lib-askgk-api.conf`のIncludeより前にも**`lib-tunnels.conf`を入れる |
| 8 | 2026-11-13 01:23 | [`d3b3abe`](https://github.com/nekoserver/lib/commit/d3b3abed22ea22e36f28bc6b754e8b231b205c67) | [#147](https://github.com/nekoserver/lib/pull/147) | Claude Opus 5.5 | +13/−3 | #6のチャットの経路の公開が無条件だった | **起動オプション`LIB_ROUTE_ACCESS_CONTROL=1`のときだけ**`lib-chat-route-access.conf`を置き、経路ID（`treeview-worker`・`aichat-panel`・`health`）のある要求だけを通す。オプションが無ければファイルを消し、libは管理者専用のまま |
| 7 | 2026-11-13 01:08 | [`ed95baf`](https://github.com/nekoserver/lib/commit/ed95baf704af8500aee4501041d6d7c52e9b8c26) | [#147](https://github.com/nekoserver/lib/pull/147) | Claude Opus 5.5 | +2/−0 | チャットの経路の呼出し元が分からなかった | **`a2enmod headers`**（経路IDのCookieに使う`mod_headers`を有効にする）。記録は`/var/log/apache2/lib-chat-via.log` |
| 6 | 2026-11-13 01:04 | [`e563864`](https://github.com/nekoserver/lib/commit/e563864c0a8912711e1ec58b6decd112b7f3ccbe) | [#147](https://github.com/nekoserver/lib/pull/147) | Claude Opus 5.5 | +8/−12 | #4で、vhostが`/lib`を管理者専用にしているときはチャットの経路を入れないようにしたため、tree-view・AIチャットのパネルが403のまま | **`lib-chat.conf`をvhostの拒否の後でIncludeし、チャットの4経路だけを暫定で許可**（#8で起動オプションのときに限った） |
| 5 | 2026-11-13 00:56 | [`486d6ac`](https://github.com/nekoserver/lib/commit/486d6aca8eee306cfccabcaa38e6d8f810110d67) | [#147](https://github.com/nekoserver/lib/pull/147) | Claude Opus 5.5 | +3/−0 | コンテナの再起動のたびに、本体リポジトリのClaude Codeのhooksが動かなくなっていた（`node_modules`が自分自身を指すsymlink） | **最後に`restore-claude-hooks.sh`を呼ぶ**。失敗しても前の段は戻さない |
| 4 | 2026-11-13 00:25 | [`f18eb46`](https://github.com/nekoserver/lib/commit/f18eb46e69a6f3d17c40094588b3e9e580ec2349) | [#147](https://github.com/nekoserver/lib/pull/147) | Claude Opus 5.5 | +32/−9 | 新しいデモイメージが元の`tunnels.rb`への`ScriptAliasMatch`を持ち、元のworker・observerを同じソケットで起動していた。vhostは`/lib`を管理者専用にした（2026-11-11） | **イメージの`ScriptAliasMatch`より前に**`lib-tunnels.conf`を入れる。**元のworker・observerを止めてから**Claude版を起動する |
| 3 | 2026-11-06 01:12 | [`c6172b9`](https://github.com/nekoserver/lib/commit/c6172b9c0420755eb5f9e36dd648a43395a490fe) | [#109](https://github.com/nekoserver/lib/pull/109) | Claude Opus 5.5 | +20/−2 | `apache2ctl`がsystemctlへ渡し、「Running in chroot, ignoring command」で0を返して、Apacheが止まったまま・古い設定のままだった | **`/usr/sbin/apache2 -k start|graceful`で直接操作**し、`configtest`の後に8443の待ち受けを確かめる |
| 2 | 2026-11-02 11:37 | [`029811f`](https://github.com/nekoserver/lib/commit/029811f8e0e793066b56dfe4e50d9c6bf7ba8ec9) | [#106](https://github.com/nekoserver/lib/pull/106) | Claude Opus 5.5 | +17/−4 | AIチャットのパネルの埋め込みページと`/lib/api/chat/*`が、`server.js`のデモの固定JSONになっていた。ストリームのサーバーも動いていなかった | **`lib-chat.conf`**（`RewriteEngine On`の直後でInclude）と**ストリームのサーバー（8091・8092）の起動**。`ops/*.py`・`chat`・`conversation-embed.html`も複製する |
| 1 | 2026-11-02 05:08 | [`f0493d5`](https://github.com/nekoserver/lib/commit/f0493d58e110f5508ab972d86352d154eaae65dd) | [#103](https://github.com/nekoserver/lib/pull/103) | Claude Opus 5.5 | +43/−0 | 再起動後、`/neko askgk`が「tunnelsの応答にreplyが含まれていません」で失敗（Apacheが全パスを`server.js`へ送っていた） | **作成**。`lib/api`・`lib/claude/api`の複製、`lib-secrets.conf`（0600）、`lib-tunnels.conf`（`ProxyPass /`より前、CGIのタイムアウト330秒）、worker・observerの起動。何度実行してもよい |

### スクリプトを変えずに、カバー範囲を変えたコミット

スクリプトが置く設定ファイルだけを変えたコミット。スクリプトの履歴には出ない。

| 日時（UTC） | コミット | PR | エージェント | 変えたファイル | 追加でカバーしたこと |
|---|---|---|---|---|---|
| 2026-11-18 21:38 | [`747fa96`](https://github.com/nekoserver/lib/commit/747fa96f457fbd3aed412509ce7b19ef3a54d0c1) | [#154](https://github.com/nekoserver/lib/pull/154) | Claude Opus 5.5 | `claude/ops/apache-lib-tunnels.conf` | イメージからtunnels APIの例外が消え、askgkが403になった。**公開側の`^/lib/api/tunnels$`を、署名ヘッダーがあるときだけ通す**例外をlib側に持たせた |
| 2026-11-02 00:40 | [`b869b22`](https://github.com/nekoserver/lib/commit/b869b22bc807205e56e3eaa63c31db68908740b4) | [#101](https://github.com/nekoserver/lib/pull/101) | Claude Opus 5.5 | `claude/ops/start-llm-worker-claude.sh`ほか | スクリプトより前。#1から呼ぶworkerの起動スクリプトを作った |

---

## 3. 今カバーしている範囲

**対象**: 今のスクリプトが行う処理 — どのコミットで入り、何で確かめているか。「#1」などは2章の表の#の列（PR番号ではない）。

| 段 | 処理 | 入った変更（2章の#） | テスト（`claude/test/`） | 実物での確認（2026-11-18） |
|---|---|---|---|---|
| 0 | `ORIGIN_HMAC_SECRET`とトークン（`LIB_TUNNELS_CF_TOKEN`、無ければ`CF_CONTAINER_API_TOKEN`）が無ければ止まる | #1 | `restore_claude_host_test.py` | — |
| 1 | `/var/www/html/lib`の用意。bind mountなら何もしない、そうでなければ`api`・`claude/api`・`ops/*.py`・`chat`・`conversation-embed.html`を複製 | #1・#2・#11 | 同上 | bind mountを検出して複製を飛ばした |
| 2 | `/etc/apache2/lib-secrets.conf`（0600） | #1 | 同上 | — |
| 3 | `lib-tunnels.conf`を置き、イメージの`ScriptAliasMatch`・`lib-askgk-api.conf`のInclude・`ProxyPass /`のうち最初のものより前でInclude | #1・#4・#9（設定の中身は`747fa96`） | 同上、`apache_lib_tunnels_test.py` | 署名なし403、不正な署名401、署名付きの一覧・`message`・`ask_id`が200 |
| 4 | `lib-chat.conf`を`RewriteEngine On`の直後でInclude。起動オプションが`1`なら`lib-chat-route-access.conf`を置き、そうでなければ消す | #2・#6・#8 | `restore_claude_host_test.py`、`apache_lib_chat_test.py` | `?via=aichat-panel`は401（チャットのサーバーに届く）、`?via=bogus`は403 |
| 5 | 8445（`010-lib.conf`）に会話ストリームの中継が無ければ`lib-internal-chat.conf`をInclude | #10 | `restore_claude_host_test.py`、`apache_lib_internal_chat_test.py` | イメージの側に中継があり、何もしなかった |
| 6 | `a2enmod headers`、`apache2ctl configtest`、`apache2 -k start|graceful`、8443の確認 | #3・#7 | — | `Syntax OK`、`listening on 8443` |
| 7 | 元のworker・observerを止め、Claude版のworker・observerとストリームのサーバーを起動（動いていれば起動し直さない） | #1・#2・#4 | — | 2回目の実行で4つとも`already running` |
| 8 | 本体リポジトリのhooksの復元（`restore-claude-hooks.sh`）。2026-11-19から、どのディレクトリでも働くガードを`~/.claude/settings.json`へ書き、全体テストのガードが実際に止めることを確かめる（[`SPEC.claude.20261119.restore-claude-hooks.md`](SPEC.claude.20261119.restore-claude-hooks.md)） | #5 | `restore_claude_hooks_test.py` | `hooks: OK`が5件（2026-11-19は`hooks: works`も） |

呼び出し元: 本体のentrypointが、`/root/lib`が届くまで待ってからbind mountと復元を行う（本体`containers/demo/lib-restore-wait.sh`、`entrypoint.sh:388`、本体コミット`2fc8110c`、2026-11-18）。ログは`/tmp/restore-claude-host.log`。

`LIB_RESTORE_NO_START=1`で段6〜8を飛ばす（テスト用）。`LIB_WWW`・`LIB_APACHE_DIR`・`LIB_APACHE_SITE`で置き場所を変えられる（テスト用）。

---

## 4. カバーしていないこと

**対象**: 復元が戻さないもの・確かめていないもの。

| 項目 | 内容 |
|---|---|
| 8445の拒否の表 | 本体SPEC 2026-11-13の拒否（`/lib/.git`・`/lib/ops`・`/lib/test`、`.py`・`.md`など）は入れない。bind mountの後は、管理者の入口から`.git/config`やソースが読める（`../EVAL.lib.20261118.opus-5.5.md`のREQ-DEP-3） |
| 起動オプションの渡し忘れ | 手で実行し直すとき、`LIB_ROUTE_ACCESS_CONTROL`が未設定だと、警告なしに`lib-chat-route-access.conf`を消す（チャットの経路が403に戻る）。entrypointから呼ばれるときは起動時の環境のまま |
| Cloudflare Tunnel | cloudflaredの起動・設定はしない（entrypointの担当）。`cfc-tunnel`は意図して停止中で、扱わない |
| Museの実行権限 | `muse/`のスクリプトの実行権限は直さない。シェバンのある5本が`100644`で、うち`tailnet-health.sh`は作られたとき（2026-11-18）から実行できず、ダッシュボードの「tailnet」が空（`../EVAL.lib.20261118.opus-5.5.md`のREQ-MUSE-1） |
| 常駐プロセスの監視 | 起動するだけで、落ちたら戻さない（systemdが無い）。もう一度実行すれば起動する |
| コンテナの再作成 | 2026-11-19に確かめ直した: コンテナは2026-11-18 22:10:12に起動し、entrypointの呼んだ復元のログ（`/tmp/restore-claude-host.log`、22:22:50）で、段1〜8が1回で最後まで通っている（bind mountの検出、経路のアクセス制御on、8445は「already relays」、4つの常駐プロセスの起動、`npm ci`とフック5件のOK）。ただし、これは#12（PR #161）より前のスクリプトで、ユーザーの設定へのフックの書き込みは、作り直しの直後には未確認 |
| 公開URL・本体ワーカーから | Cloudflare経由・本体ワーカー経由の結果は、2026-11-18には確かめていない（コンテナの中から8443・8445へ送っただけ） |

---

## 5. 要件の番号（2026-11-19に付与）

3章の段ごとの処理を、評価のための要件にする。

| 番号 | 要件 | 3章の段 |
|---|---|---|
| REQ-RCH-1 | `ORIGIN_HMAC_SECRET`とトークンが無ければ止まる | 0 |
| REQ-RCH-2 | bind mountなら複製しない。そうでなければ決まったファイルを複製する | 1 |
| REQ-RCH-3 | `lib-secrets.conf`を0600で書く | 2 |
| REQ-RCH-4 | tunnels APIのIncludeを、イメージの`ScriptAliasMatch`・`lib-askgk-api.conf`・`ProxyPass /`のうち最初のものより前に置く | 3 |
| REQ-RCH-5 | チャットのIncludeを`RewriteEngine On`の直後に置き、起動オプションが`1`のときだけ経路の許可を置く | 4 |
| REQ-RCH-6 | 8445に中継が無ければ足し、あれば何もしない | 5 |
| REQ-RCH-7 | Apacheを`apache2 -k`で起動または`graceful`し、8443を確かめる | 6 |
| REQ-RCH-8 | 元のworker・observerを止め、Claude版の4つの常駐プロセスを起動する（動いていれば何もしない） | 7 |
| REQ-RCH-9 | 最後にフックを復元する。失敗しても前の段は戻さない | 8 |
| REQ-RCH-10 | 何度実行してもよい（Includeを重ねない） | 全体 |

## 改訂の記録

| 日付 | モデル | 箇所 | 内容 | 根拠 |
|---|---|---|---|---|
| 2026-11-19 | opus-5.5 | 2章・3章の段8 | PR #161の行を追加、段8の説明を更新（段8の更新は#161と同じ変更） | `git log -- claude/ops/` |
| 2026-11-19 | opus-5.5 | 4章 | コンテナの再作成の行を、起動時のログで確かめ直した内容に更新 | `/tmp/restore-claude-host.log`、`uptime -s` |
| 2026-11-19 | opus-5.5 | 5章 | 要件の番号を追加 | — |
