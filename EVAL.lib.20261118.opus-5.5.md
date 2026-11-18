# 評価: libリポジトリの現状（2026-11-18、opus-5.5）

評価日: 2026-11-18（UTC、22:30〜22:45ごろ）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.lib.20261118.opus-5.5.md`](SPEC.lib.20261118.opus-5.5.md)（SHA256 `6ad0896a039f8b0e17d6c968f2cf2977a63fa0c57e4e50700c49c659afa35f4d`）
評価対象: `nekoserver/lib`の`main`（`14e82cb1f7869bb9e09a5880f1e1b7237df5abc1`、作業ツリーの変更はSPEC・EVALの追加だけ）と、本体のdemoコンテナで動いている状態（同日に`restore-claude-host.sh`を`LIB_ROUTE_ACCESS_CONTROL=1`で実行し直した後）

この文書はtree-viewのSPEC評価（`ops/spec_eval.py`）を通さずに作った。そのため、先頭の監査メタデータ（`<!-- tree-view-spec-eval … -->`）は無く、observerの受付記録とも結び付いていない。

---

## 総合

**対象**: SPECの要件全体 — どこまで満たしているか。

中心の機能は動いている。公開側の制限（403）、tunnels APIの例外、署名付きの一覧・`message`・`ask_id`、復元スクリプト、`lib/claude`のテストは、どれもSPECどおりだった。

未充足は2つ。

1. **Museのスクリプト7本が、gitで実行権限を失っている（REQ-MUSE-1）。** 2026-11-18の2つのコミットで`100755`から`100644`に戻った。その結果、**ダッシュボードの「tailnet」の区画が空になる**（Apacheの`www-data`から`Permission denied`）。テスト2件が落ちて検出している。
2. **8445で、リポジトリの管理用のファイルが読める（REQ-DEP-3）。** bind mountになったため、`.git/config`・ソース・`CLAUDE.md`が管理者の入口から200で返る。SPECでは既知の状態（目標、未実現）として扱っている。

| 区分 | 要件の数 | 要件 |
|---|---|---|
| 充足 | 22 | DOC-1、ACC-1〜5、DEP-1・2、RST-1〜6、TUN-1〜4（TUN-4は設定のみ）、MUSE-2（テストのみ）、REPO-1・3・4 |
| 未充足 | 2 | MUSE-1、DEP-3（目標） |
| 一部充足 | 2 | TEST-1（コードの失敗2件と既知の失敗2件が残る）、REPO-2（テストが落ちる状態がmainにある） |
| 未確認 | 1 | MUSE-3（ほかにSPEC 9章の各項目） |

---

## 要件ごとの評価

**対象**: SPECの`REQ-…`の一つひとつ — 根拠と、行った確認。

### 1・2章: 文書、入口と制限

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-DOC-1 | 充足 | SPECの1章・3章に、`SPEC.lib.20261118.lib-features-access.md`の7章が古いことを書いた。既存のSPECは変えていない（`git status`はSPEC・EVALの追加だけ） |
| REQ-ACC-1 | 充足 | 8443への`GET`で、`/lib/date.shtml`・`/lib/ip.shtml`・`/lib/tunnels.cgi`・`/lib/muse/dashboard/index.shtml`・`/lib/keys/`・`/lib/ops/llm_worker.py`・`/lib/CLAUDE.md`・`/lib/.github_token`・`/debug`・`/admin`がすべて403。設定は`000-demo.conf`の`<LocationMatch "^/(?:debug|admin|lib)(?:/|$)">`の`Require all denied` |
| REQ-ACC-2 | 充足 | 8443で、署名ヘッダーなし403、不正な署名401（`{"error":"unauthorized","reason":"bad_signature"}`）、正しい署名200。署名ヘッダー付きでも`/lib/api/tunnels/extra`・`/lib/api/tunnels.rb`は403。設定は`claude/ops/apache-lib-tunnels.conf:16-18`。`claude/test/apache_lib_tunnels_test.py`が通る |
| REQ-ACC-3 | 充足 | 8443の`/lib/conversation-embed.html?via=aichat-panel`は401（チャットのサーバーに届いてログインを求める）、`?via=bogus`は403。`/etc/apache2/lib-chat-route-access.conf`の`Require env LIB_CHAT_VIA_KNOWN`。起動オプションが無い場合（ファイルを消す側）は、今回は実物で試していない（`claude/test/apache_lib_chat_test.py`は通る） |
| REQ-ACC-4 | 充足 | `010-lib.conf`の`Listen 127.0.0.1:8445`と`<Directory /var/www/html/lib>`の`Require local` |
| REQ-ACC-5 | 充足 | `api/tunnels_lib.rb:313-314`で、`message`・`ask_id`・LLMへの要求は`require_hmac: true`。署名なしの要求はApacheの段で403になるため、8443からはCGIまで届かない |

### 3章: 配置

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-DEP-1 | 充足 | `findmnt /var/www/html/lib`は`/dev/vdc[/root/lib]`。`restore-claude-host.sh:32`の`[ "$LIB" -ef "$WWW" ]`で複製を飛ばし、実行の出力は`lib: /var/www/html/lib is the lib checkout itself (bind mount), nothing to copy`。bind mountでない場合は`claude/test/restore_claude_host_test.py`が確かめる |
| REQ-DEP-2 | 充足 | `restore-claude-host.sh:76-79`。今の`010-lib.conf`はイメージの側で中継を持ち（`lib-internal-chat`のIncludeは0件）、実行の出力は`the internal lib vhost already relays the conversation stream`。8445の`/lib/conversation-embed.html`・`/lib/chat/app.mjs`は401（チャットのサーバーの`authentication_required`）、`/lib/api/chat/session`は403（`origin_rejected`）で、どれもチャットのサーバーまで届いている |
| REQ-DEP-3（目標） | **未充足（既知）** | 8445への`GET`で、`/lib/.git/config`・`/lib/.git/HEAD`・`/lib/ops/llm_worker.py`・`/lib/claude/ops/restore-claude-host.sh`・`/lib/keys/register.rb`・`/lib/CLAUDE.md`が200。`/lib/api/tunnels`は`tunnels.rb`のソースを文字のまま返す（`api/tunnels`はsymlinkで、8445ではCGIとして実行されない）。`.github_token`はこのチェックアウトに無く404、`.git/config`のremoteに認証情報は含まれていない（`https://github.com/nekoserver/lib`）。入口Bの管理者だけが届く範囲 |

### 4章: 復元

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-RST-1 | 充足 | 同じコンテナで起動時と今回の2回実行した。`000-demo.conf`の`Include …lib-tunnels.conf`・`Include …lib-chat.conf`はどちらも1件。2回目の出力は`worker already running`など、4つの常駐プロセスを起動し直していない |
| REQ-RST-2 | 充足 | `restore-claude-host.sh:44-46`（`umask 077`、`chmod 0600`）。秘密の値はリポジトリに無い |
| REQ-RST-3 | 充足 | `000-demo.conf`で、`Include /etc/apache2/lib-chat.conf`（35行目）・`Include /etc/apache2/lib-tunnels.conf`（40行目）が`ProxyPass /`（42行目）より前。`claude/test/restore_claude_host_test.py`がIncludeの位置を確かめる |
| REQ-RST-4 | 充足 | `restore-claude-host.sh:96-100`（`/usr/sbin/apache2 -k`）。実行で`Syntax OK`・`apache: listening on 8443` |
| REQ-RST-5 | 充足 | `restore-claude-host.sh:131`。実行の出力は`hooks: OK`が5件（`check-migration-table-registry.js`・`claude-full-test-guard.js`・`claude-japanese-guard.js`・`claude-push-guard.js`・`claude-self-check-guard.js`）。`node_modules`があるため今回は`npm ci`しなかった（起動時のログ`/tmp/restore-claude-host.log`では`node_modules rebuilt with npm ci`）。`claude/test/restore_claude_hooks_test.py`が通る |
| REQ-RST-6 | 充足（運用） | 今回のシェルでは`LIB_ROUTE_ACCESS_CONTROL`が未設定だった。`/etc/apache2/lib-chat-route-access.conf`があることを確かめてから`=1`を渡し、出力は`route access control: on`。**そのまま実行すると黙って`off`になる**ので、手で実行し直す人が間違えやすい |

### 5章: tunnels API

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-TUN-1 | 充足 | 8443への署名付き`GET`が200、約1.2秒。`tunnels`は3件（`nekoroot` healthy、`term-root` healthy、`cfc-tunnel` down）、`auth: api_token`、`fetched_at`あり |
| REQ-TUN-2 | 充足 | 署名付き`POST {"message":"いま down になっているトンネルはどれ？一文で答えて"}`が200、約8.7秒。`via: claude`・`ask_status: done`・`llm_model: claude-opus-5-5`・`llm_effort: low`、`reply`は「現在 down になっているのは `cfc-tunnel`（…接続数 0）だけです」。一覧と一致するので、トンネル一覧がプロンプトに添えられている |
| REQ-TUN-3 | 充足 | 署名付き`POST {"ask_id":"claude-cc72b1f2-…"}`が200、同じ`reply`と`ask_status: done` |
| REQ-TUN-4 | 充足（設定）、300秒の実待ちは未確認 | `claude/api/tunnels.claude.rb:17`の`WAIT_SECONDS = 300`、`apache-lib-tunnels.conf:10`の`CGIDScriptTimeout 330`。300秒かかる応答は試していない |

`cfc-tunnel`のdownは、SPECの5章のとおり期待状態（`cf-container/SETTING.cf-container.md:176`）。ただし、CloudflareのAPIの`conns_inactive_at`は`2026-11-18T13:33:09Z`で、同日まで何かが接続していた。接続元はこのコンテナからは確かめられない（SPEC 9章）。

### 6章: Muse

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-MUSE-1 | **未充足** | `git ls-files -s muse`で、シェバンのある`muse/hooks.sh`・`muse/samples/receiver.py`・`muse/sdk-ask-cgi.py`・`muse/sdk-auto-approve.py`・`muse/sdk-common.sh`・`muse/sdk-ts-common.sh`・`muse/tailnet-health.sh`が`100644`。原因のコミットは`7fb2b20`（2026-11-18「muse: 送信者検証付き自動承認を upstream へ取り込む」、`sdk-ask-cgi.py`を`100755 => 100644`）と`7399ca0`（同日「receiver: 鍵照合を稼働中実装(muse-vm)に統一…」、`receiver.py`を`100755 => 100644`）。11-11の`8ef26c5`で付けた実行権限が戻っている。**影響を実物で確認した**: 8445の`/lib/muse/dashboard/tailnet.shtml`は空の本文を返し、`www-data`で`../tailnet-health.sh`を実行すると`Permission denied`。同じダッシュボードの`status.shtml`（`muse-status.sh`は`100755`）は正常に出る。テスト`ScriptRulesTest.test_scripts_are_executable_in_git`・`test_every_file_with_a_shebang_is_executable_in_git`が落ちて検出している |
| REQ-MUSE-2 | 充足（テスト） | `test/muse_scripts_test.py`の原則の検査（状態を変えるコマンドを使わないなど）は通る。muse-vmの実環境では確かめていない |
| REQ-MUSE-3 | 未確認 | 受付・承認・実行の経路は今回動かしていない。`muse/SPEC.md`の6章の検証（muse-vm上）に頼る |

### 7章: リポジトリの約束

| 要件 | 結果 | 根拠・確認 |
|---|---|---|
| REQ-REPO-1 | 充足（今回の範囲） | SPEC・EVALの作成で、変数・設定を足していない |
| REQ-REPO-2 | 一部充足 | `main`に、テストが落ちる状態（REQ-MUSE-1の2件）が入っている。11-18のコミットが、テストの失敗を残したままマージされたことになる |
| REQ-REPO-3 | 充足（形） | `test/containers_doc_test.py`・`NoticeToMuseTest`は通る。中身が変更に追いついているかは見ていない |
| REQ-REPO-4 | 充足 | `.gitignore`に`.github_token`がある |

### 8章: テスト

| 種類 | 結果 |
|---|---|
| Python（lib、`discover -s test`） | 183件、失敗3、skip 7（`*_live_test.py`など） |
| Python（lib/claude） | 89件、すべて成功 |
| Ruby | `llm_prompt_test.rb` 17件、`railway_exec_test.rb` 5件、`tunnels_claude_test.rb` 6件、`claude/test/tunnels_claude_rb_test.rb` 7件、すべて成功。`hmac_auth_env_test.rb`は読み込みで失敗（`cannot load such file -- minitest/mock`） |
| Node（`node --test test/*_test.mjs`） | 48件、失敗2 |

失敗の内訳:

| テスト | 原因 | 区分 |
|---|---|---|
| `muse_scripts_test.ScriptRulesTest`の2件 | REQ-MUSE-1（実行権限が外れた） | **コードの失敗** |
| `muse_scripts_test.GitHeadsTest.test_reports_branch_head_dirty_and_unpushed` | テストは`PATH`を`<偽物>:/usr/bin:/bin`に絞るが、このコンテナの`git`は`/usr/local/bin/git`だけ。`git-heads.sh`を手で実行すると期待どおりの行を出す | 環境の不足 |
| `hmac_auth_env_test.rb` | minitest 6.0.0では`minitest/mock`が本体から外れている | 環境の不足（gemの版） |
| `chat_session_cookie_test.mjs`の2件 | `ReferenceError: location is not defined`。2026-11-04のSPEC（`SPEC.lib.20261104.console-stream-adhoc.md`の「実測結果」）に書かれている既知の失敗のまま | 既知の失敗（未修正） |

REQ-TEST-1は**一部充足**。環境の不足を除いても、コードの失敗2件と既知の失敗2件が残る。

---

## 提案（未実施）

**対象**: 未充足・一部充足の要件を満たすための変更 — この評価では何も変えていない。

| 優先 | 内容 | 対応する要件 |
|---|---|---|
| 1 | `git update-index --chmod=+x`で7本に実行権限を戻す。muse-vmに配る経路で権限が落ちないかも確かめる。`muse/NOTICE-TO-MUSE.md`に書き足す（CLAUDE.mdの約束） | REQ-MUSE-1、REQ-REPO-2・3 |
| 2 | 本体のイメージの`010-lib.conf`に、本体SPEC 2026-11-13の拒否の表（少なくとも`/lib/.git`、`/lib/ops`、`/lib/test`、`.py`・`.rb`・`.md`）を入れる | REQ-DEP-3 |
| 3 | `restore-claude-host.sh`を手で実行し直すとき、`LIB_ROUTE_ACCESS_CONTROL`の渡し忘れで黙って`off`にならないようにする。例えば、未設定で今のファイルがあるときは警告して止める。設定スイッチは足さない（CLAUDE.mdの約束） | REQ-RST-6 |
| 4 | `GitHeadsTest`の`PATH`に`git`の実際の場所を加える。`hmac_auth_env_test.rb`は`minitest-mock`を使うか、mockに頼らない形にする | REQ-TEST-1 |
| 5 | `chat_session_cookie_test.mjs`の`location`の未定義を直す（2週間放置されている） | REQ-TEST-1 |

---

## 確かめていないこと

- 入口B・Cを実際に通した結果。8445への要求は、すべてコンテナの中から直接送った。
- 公開URL（`https://mygw.nekomaneki.work`、Cloudflare経由）での結果。8443への要求は`https://127.0.0.1:8443`へ送った。
- Slackからの`/neko askgk`。
- `LIB_ROUTE_ACCESS_CONTROL`が無いときの公開側のチャットの経路（今回は`on`のまま評価した）。
- コンテナの再作成後の復元。
- `cfc-tunnel`の接続元と、13:33 UTCの切断の理由。
