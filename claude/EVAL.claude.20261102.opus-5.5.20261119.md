# 評価: lib/claude の別名版（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC、00:30〜01:10ごろ）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.claude.20261102.md`](SPEC.claude.20261102.md)（2026-11-19の改訂版、SHA256 `d09d847c371ad044f59d9a4cc9b0abceb489278c59a648008be021f355c5eca2`）
評価対象: `nekoserver/lib`の`main`（`592f438`、作業ツリーの変更はSPEC・EVALだけ）と、本体のdemoコンテナ（`mygw.nekomaneki.work`、2026-11-18 22:10起動）で動いている状態
区分: [`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順1（11-02のEVAL[`EVAL.claude.20261102.md`](EVAL.claude.20261102.md)はモデル名が無い。作成のコミットはClaude Opus 5.5）

この文書はtree-viewのSPEC評価（`ops/spec_eval.py`）を通さずに作った。libはspec-evalの対象リポジトリに入っていない（REQ-CL-14）。

---

## 総合

**対象**: 改訂したSPECの要件（REQ-CL-1〜26）全体。

別名版の中心（tunnels API、Claude・Museへの振り分け、observer、復元、入口の制限）は、公開側のApacheを通した実測でSPECどおりに動いた。テストは`claude/`の3種類がすべて通った。

11-02の版は、23コミット分の変更（muse_prompt、bridge_jobs、agent-tools、入口の制限、復元の変更）を書いておらず、`cf tunnels list --json`・「workerは手動起動」など古い記述があった。改訂で直した（SPECの「改訂の記録」）。

| 区分 | 数 | 要件 |
|---|---|---|
| 充足 | 18 | CL-2〜6、CL-9〜12、CL-15〜22、CL-26 |
| 充足（テストのみ） | 5 | CL-7・8・13・23・24 |
| 一部 | 2 | CL-1（元ファイルを1件変えた）、CL-14（inspectは動く。createはEVALの保存まで完了しない。SPECが「未対応」と書いているとおり） |
| 充足（静的な確認） | 1 | CL-25 |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-CL-1 | 一部 | 11-02の版（`029811f`）より後に`claude/`を変えた23コミット（マージを除く）のうち、`e2bcaa1`（muse_prompt、2026-11-06）だけが元ファイル`api/llm_prompt.rb`を変えた（エンジンの一覧とIDの形に`muse`を足した）。差し替えでは済まない部分（tunnels APIの振り分け）で、元のホストでも`muse_prompt`を受け付けるようになった（元のworkerは`unsupported_engine`で断る）。ほかの22コミットは元ファイルに触れていない（`git show --name-only`で確認） |
| REQ-CL-2 | 充足 | `ruby claude/test/tunnels_claude_rb_test.rb`が7件通過（2回読み込み、`run!`しないことを含む） |
| REQ-CL-3 | 充足 | 公開側Apache（8443）へ署名付きの一覧の要求が200、`auth: api_token`、`error: null`、トンネル3件（`nekoroot` healthy・接続3、`cfc-tunnel`・`term-root` down・接続0）。コンテナの`cf`は`1.0.0-rc.1`に上がっていたが、取得できた。rc.1の出力の形そのもの（`result_info:`の行の有無）は、`cf`を直接呼ぶ確認が権限の判定で止められたため見ていない |
| REQ-CL-4・5 | 充足 | 署名付き`message`「いま down になっているトンネルはどれ？一文で答えて」が200、7.5秒、`via: claude`、`llm_model: claude-opus-5-5`、`llm_effort: low`、`reply`は「`cfc-tunnel` と `term-root` の2つが down（接続数0）で、`nekoroot` だけが healthy」。一覧と一致するので、一覧がプロンプトに添えられている |
| REQ-CL-6 | 充足 | `apache-lib-tunnels.conf`の`CGIDScriptTimeout 330`、`LlmPrompt::WAIT_SECONDS = 300`（コード）。300秒かかる応答は試していない |
| REQ-CL-7・8 | 充足（テストのみ） | `llm_worker_claude_test.py`（helperのbindの順序、`/root`のtmpfs）。sandboxの中を実際に見る確認は今回はしていない（11-02に実施） |
| REQ-CL-9 | 充足 | 署名付き`muse_prompt="PONG とだけ答えて"`が200、21.6秒、`via: muse`、`llm_model: muse`、`reply: "PONG"`（前後の空白なし）。`llm_worker_muse_test.py`が到達の確認・失敗の理由・鍵の除去を確かめている |
| REQ-CL-10 | 充足 | observerのプロセスの環境は`LIB_CHAT_CLAUDE_SESSION=workspace:/root`。切替のファイル（`claude-source.json`）は無い |
| REQ-CL-11・12 | 充足 | observerのソケットへ`{"op":"watch"}`を送り、`type: conversation`、`status: active`、タイトルとメッセージ32件のスナップショットが返った。最後の項目は`role: assistant`・`phase: commentary`（ターンの途中） |
| REQ-CL-13 | 充足（テストのみ） | `chat_observer_claude_test.py`。実際の送信は今回はしていない（人が操作中のセッションに書き込むため） |
| REQ-CL-14 | 一部 | observerへの`spec-eval inspect`（本体の`SPEC.cloudflare-workers-github-oauth-1.20260313.diff.md`）は`available: true`、`connected: true`。libは`evaluation_unavailable`（既定の対象外）。createは試していない（EVALの保存まで完了しないことがSPECに書かれており、依頼を送ると監視中のセッションに書き込むため） |
| REQ-CL-15 | 充足 | `stream_routes.py endpoints`が`mygw.nekomaneki.work`の5つのURL、`worker --id demo`が`[{"id": "demo", "origin": "https://mygw.nekomaneki.work"}]` |
| REQ-CL-16 | 充足 | ストリームのサーバー（pid 860）の環境: `LIB_CHAT_ORIGINS=https://mygw.nekomaneki.work`、`LIB_CHAT_FRAME_ORIGINS`はそれに本体Workerの2つのorigin |
| REQ-CL-17 | 充足 | 8443の`/lib/api/tunnels`: 署名なし403、不正な署名401（`unauthorized`）、署名付き200。`/lib/api/tunnels/extra`は署名ヘッダー付きでも403 |
| REQ-CL-18 | 充足 | 8443: 埋め込みページの`?via=aichat-panel`は401（アプリに届く）、`?via=bogus`・経路IDなしは403、`/lib/api/chat/session`は`?via=`だけでは403で、Cookie`lib_chat_via=treeview-worker`付きは401（アプリに届く）。`/etc/apache2/lib-chat-route-access.conf`がある（起動オプションon） |
| REQ-CL-19〜21 | 充足 | 起動時のログ`/tmp/restore-claude-host.log`（22:22:50）: bind mountを検出して複製なし、`Syntax OK`、`listening on 8443`、4つの常駐プロセスの起動。`restore_claude_host_test.py`が通過。`lib-secrets.conf`は0600 |
| REQ-CL-22 | 充足 | 2026-11-19に`restore-claude-hooks.sh`を実行し、`hooks: works`。同じセッションで全体テストのガードが`npx vitest run`を止めた（[`EVAL.claude.20261119.restore-claude-hooks.opus-5.5.20261119.md`](EVAL.claude.20261119.restore-claude-hooks.opus-5.5.20261119.md)） |
| REQ-CL-23・24 | 充足（テストのみ） | `bridge_jobs_test.py`（SQLiteで本番と同じSQL）。本番のD1では動かしていない |
| REQ-CL-25 | 充足（静的な確認） | `claude/ops/agent-tools/.gitignore`が`state/`。リポジトリに状態ファイルは無い |
| REQ-CL-26 | 充足 | Python 96件、Ruby 7件（31 assertions）、Node 1件、すべて通過 |

---

## 11-02のEVALとの違い

| 11-02のEVALの指摘 | 今 |
|---|---|
| `message`付きの要求が最大300秒待ち、Cloudflare経由で打ち切られる恐れ | 残っている（REQ-CL-6）。Museへの経路は、届かないときに10秒で失敗を返すようにした（REQ-CL-9） |
| SPECの記述が実装に追いついていない | 11-02から18日分の差が開いていた。今回の改訂で直した |
| workerは手動起動、コンテナの再起動で止まる | entrypointが起動時に復元を呼ぶようになった（REQ-CL-19） |
| SUGGESTの12件は未着手 | 本評価の対象外（SPECの要件ではない） |

---

## 提案（未実施）

1. REQ-CL-1の例外（`api/llm_prompt.rb`への`muse`の追加）を、SPECに例外として書くか、別名版の側で差し替える形に戻すかを決める（利用者の判断）。
2. `cf 1.0.0-rc.1`の`tunnels list`の出力の形を、実物で確かめて`tunnels_claude_rb_test.rb`の契約に足す（今のテストはbeta.31の形）。
3. spec-evalの対象にlibを足すか、足さないならlibのSPECは[`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順で評価する、とtree-view側にも書く。

---

## 確かめていないこと

- Slackからの`/neko askgk`（Worker → rust-worker-sqlx-d1 → tunnels API）。今回は、コンテナの中から公開側のApacheへ同じ形の署名付き要求を送った。
- 300秒近くかかるLLMの応答。
- observerの送信と、spec-evalのcreate。
- bridge_jobs.pyの本番のD1での実行。
- `cf 1.0.0-rc.1`の出力の形。
