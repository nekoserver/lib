# 評価: lib/claudeの現状の実装

評価日: 2026-11-02
評価対象: `lib/claude`の未コミットの作業ツリー（`api/tunnels.claude.rb`、`ops/chat_observer_claude.py`、`ops/llm_worker_claude.py`、`ops/claude-helper.sh`、`ops/*.service`、`ops/start-llm-worker-claude.sh`、`test/chat_observer_claude_test.py`）
評価の基準: [`SPEC.claude.20261102.md`](SPEC.claude.20261102.md)（仕様どおりか）、[`SUGGEST.claude.20261102.md`](SUGGEST.claude.20261102.md)（Claude Code固有の機能をどこまで使えているか）

## 追記: 実装状況にもとづくSPECの再評価（2026-11-02、PR #103・#104の後）

**対象**: `main`（PR #103マージ後）の`lib/claude`と、このコンテナで動いている状態（`restore-claude-host.sh`で構成） — SPECの各記述が今の実装・動作と合っているかを、コードと実行結果で確かめ直した。以下の本文（「総合評価」以降）はPR #103より前の評価として残す。

### 総合

SPECの中心である「元ファイルを変えずに、本番の配置がないホストでtunnels API・worker・observerを動かす」は満たしている。再起動後の復元がスクリプト1本で再現でき、Apache経由（Slackと同じ入口）でClaudeが正しい内容で答えるところまで確認した。前回の不具合1・2・4は直っており、テストも差し替え部分を押さえている。

一方で、SPECの記述が実装に追いついていない箇所がいくつかある（下の「SPECの記述の不整合」）。また、`message`付きの要求が`wait_seconds`を無視して最大300秒待つ点は、Cloudflare経由の経路で打ち切られる恐れがあり、SPECにも書かれていない。

| 観点 | 前回 | 今回 |
|---|---|---|
| SPECへの適合（表示・応答） | 良い | 良い。Apache経由の入口とClaudeの回答内容まで確認 |
| SPECへの適合（observerの送信） | 不具合あり | 適合（修正済み、実際の送信で確認済み） |
| 元ファイルを変えない方針 | 守れている | 守れている（PR #103の変更は`claude/`のみ） |
| テスト | 不足 | おおむね十分。差し替え部分はすべてテストあり。`wait_seconds`の扱いは未検証 |
| 運用（復元・常駐・タイムアウト） | 未整備 | 復元は整備（スクリプト）。自動起動は未対応。タイムアウトに新たな懸念 |
| SPECの記述の正確さ | — | 要修正（古い件数、矛盾、このホストに合わない「反映」） |
| Claude固有の機能の活用（SUGGEST） | 未着手 | 未着手のまま |

### SPECの記述ごとの確認

| SPECの記述 | 確認方法 | 結果 |
|---|---|---|
| 構成（ファイル一覧） | `ls`と照合 | 適合。PR #103の4ファイルも記載済み |
| tunnels: shebang・`--json`・接続数が整数 | Apache経由の`GET`でトンネル一覧を取得、テスト | 適合 |
| tunnels: 先頭なしの`message`はClaudeへ | テスト（偽のworkerソケットで投入エンジンを記録）、Apache経由の実際の質問 | 適合 |
| tunnels: Claudeへのプロンプトにトンネル一覧を添える | テスト（一覧が入り、`sanitize_tunnel`で落とす項目は入らない）、実際の質問で`term-root`停止を正しく回答 | 適合。Codexへのプロンプトは変わらないこともテストで確認 |
| tunnels: 待ちは`message`付きで300秒、`wait 0`は0 | `tunnels_lib.rb`の180行目を確認 | **記述があいまい**。待ちを決めるのは`message`キーの有無だけで、リクエストの`wait_seconds`は読んでいない。下の新たな不具合Aを参照 |
| tunnels: Webサーバーのタイムアウトを300秒超に | `apache-lib-tunnels.conf`の`CGIDScriptTimeout 330` | Apacheについては適合。その手前のCloudflareの制限は考慮されていない（不具合A） |
| askgk: 署名付きPOSTに応答、署名なしは401 | Apache経由で実行 | 適合（8〜9秒で`done`、署名なしは`401`） |
| worker: sandbox、helperのbind、`/root`は作業ディレクトリのみ | テスト5件、前回の実行結果 | 適合 |
| worker: sandbox内で`cf`が使えない | askgk経由で`cf tunnels list`を実行させた | 事実として適合（`CLOUDFLARE_ACCOUNT_IDが未設定`）。SPECはこれを前提にトンネル一覧を添える設計にした |
| observer: ソケット・プロトコル・出力の形 | 本来のソケットで`watch` | 適合 |
| observer: `workspace:`で最新の記録を追う | `workspace:/root`で起動し、`watch`でこの会話（タイトル「Tunnels.rbとobserverの復旧」）を受信 | 適合。**前回「未確認」から確認済みに変わった**。`/root`以外のパスは未確認 |
| observer: 送信、`--`、CLIの選択 | テスト、前回の実際の送信 | 適合 |
| observer: `spec-eval create` | 前回の確認のまま | SPECの記述どおり、EVALの保存まで完了しない（権限の判断待ち） |
| 復元: 4つの処理、何度実行してもよい | テスト4件（一時ディレクトリ）、vhostを元に戻してから実際に実行 | 適合。2回目の実行で`Include`が重複しないこともテストで確認 |
| 復元: 起動時のトークンでは一覧が`[]` | Apacheの環境のトークンで`cf`を実行 | 適合（2026-11-02時点） |
| stream_routes・本体Workerの台帳 | 今回は触っていない | 未再確認（テスト`stream_routes_test.py`は通過） |

### SPECの記述の不整合（直すべき箇所）

| 箇所 | 内容 |
|---|---|
| 「tunnels.claude.rb」の冒頭 | 「`message`・`ask_id`・`claude_prompt=`等の振り分けは`tunnels.rb`と同じ」とあるが、同じ節の下で先頭なしの`message`をClaudeへ送ると書いており、矛盾する。冒頭から「振り分け」を外す |
| 「検証済み」のテスト件数 | 「Python 12件、Ruby 4件」は古い。今は`claude/test`のPython 22件、Ruby 6件 |
| 「未確認・未対応」のworker | 「workerは手動起動。コンテナ再起動で止まる」は事実だが、`restore-claude-host.sh`で1回で戻せることが書かれていない |
| 「反映」 | systemdと`/var/www/html/lib/claude`への全体の配置を前提にしている。このコンテナにはsystemdが無く（PID 1は`init`）、`restore-claude-host.sh`は`api`だけを複製し、workerとobserverは`/root/lib`から起動する。このホスト向けの手順（`restore-claude-host.sh`）と、systemdのあるホスト向けの手順を分けて書く |
| 待ち時間の記述 | 「`wait 0`（投入のみ）の呼出しは0のまま」は、`wait_seconds: 0`を送れば投入だけになると読める。実際は`message`キーがあれば必ず300秒まで待つ（不具合A） |
| `/usage`・`/status` | 先頭なしの`message`をClaudeへ送るため、元ではCodexへ送る`/usage`・`/status`もClaudeにプロンプトとして渡る（`LlmPrompt.route`で確認）。SPECに記載が無い |

### 新たに見つかった問題

**A. `message`付きの要求は`wait_seconds`を無視して最大300秒待つ（重大度: 中）**

- 箇所: `api/tunnels_lib.rb`の`attach_message!`が`filters.key?('message') ? 90 : 0`で待ち時間を決め、別名版が正の値を300秒に置き換える。リクエストの`wait_seconds`は読んでいない。
- 影響: `claude/test/manual/askgk_request.rb`は「`wait_seconds: 0`で投入し、`ask_id`で照会する」と書いているが、実際には最初の要求が回答まで待つ。今回の確認がすべて1回の要求で`done`になったのはこのため。Cloudflare経由の要求は、一般にオリジンの応答を100秒程度で打ち切る（524）。100秒を超える回答では、Workerに結果が届かない恐れがある。
- 確認状況: 待ち時間の決め方はコードで確認。Cloudflareでの打ち切りと、Worker側がそれをどう扱うかは未確認（試していない）。
- 対処案（要合意）: 別名版でリクエストの`wait_seconds`を尊重する。または待ちの上限をCloudflareの制限より短くし、残りは`ask_id`の照会に任せる。どちらもWorkerとの取り決めに関わる。

**B. 復元が実行者のシェルのトークンに依存する（重大度: 中、運用）**

- 起動時のトークンでは一覧が取れないため、`restore-claude-host.sh`はClaude Codeのシェルにあるトークンを使う。このため`entrypoint.sh`から自動で実行しても、一覧が空になる。自動起動の前に、起動時のトークンの権限を直すか、トークンの渡し方を決める必要がある。

**C. その他（重大度: 低）**

| 箇所 | 内容 |
|---|---|
| `restore-claude-host.sh` | vhost（`000-demo.conf`）を直接書き換える。コンテナのイメージ側でvhostが変わると、`ProxyPass /`が見つからず止まる（その場合はエラーで終了する作り） |
| `/etc/apache2/lib-secrets.conf` | HMACの鍵とトークンを平文で置く（root、0600）。Apacheの子プロセス（`www-data`）からは読めないが、CGIの環境変数には入る。今このvhostで動くCGIは`tunnels.claude.rb`だけ |
| askgkの回答 | 前回の「`/root/lib`はコミットがない」に加え、今回も未コミットのファイルがある時点で「uncommitted changesは無い」と答えた。sandbox内の`codex-web`から見たgitの扱いによると思われる。未確認 |
| 前回の「Apacheの`Timeout 300`と同じ値」 | `CGIDScriptTimeout 330`で解消。ただし不具合Aのとおり、手前のCloudflareの制限が先に来る |

### テスト

- `claude/test`: Python 22件、Ruby 6件、すべてOK。
- 元のテスト: `test/tunnels_claude_test.rb`、`test/llm_prompt_test.rb`、`test/chat_observer_test.py`、`test/chat_websocket_test.py`、`test/llm_worker_test.py`はOK（`PYTHONPATH=ops`で直接実行。`python3 -m unittest test.…`の形では`test`がパッケージでないため読み込めない）。
- 未検証: `wait_seconds`の扱い（不具合A）、`/usage`のClaudeへの振り分け、実際のコンテナ再起動後の復元。

### SUGGESTに対する現状

前回から実装済みになったものは無い。トンネル一覧をプロンプトに添える変更は、SUGGEST 8（`sanitize_tunnel`と同じ項目だけを返すMCPツール）と同じ目的、つまり許可した項目だけをClaudeに見せるものを、より簡単な形で先に入れたものと言える。MCPにすると、Claudeが必要なときだけ取得でき、Bashを外す（SUGGEST 3）ことも検討できる。

### 推奨する対応の順

1. SPECの記述を直す（上の「不整合」の6点）。合意は要らない。
2. 不具合Aの方針を決める（`wait_seconds`を尊重するか、待ちの上限を下げるか）。Workerとの取り決めに関わるため合意が要る。決めたら、先に失敗するテストを書いてから直す。
3. Slackからの`/neko askgk`を確かめる。長い回答（100秒超）で照会の経路も通す。
4. 起動時のトークンの権限を直し、`entrypoint.sh`から`restore-claude-host.sh`を呼ぶ（不具合B、PLANの段階1）。
5. PLANの段階2（費用上限、Bashの絞り込み）。

### 確認したこと・していないこと

- 確認（2026-11-02）: 上の表の「確認方法」に書いたもの。テストの実行、Apache経由の要求（トンネル一覧、先頭なしの質問、`claude_prompt=`、`hello`、署名なしの401）、observerの`watch`、`LlmPrompt.route`での`/usage`の振り分け、`tunnels_lib.rb`の待ち時間のコード、systemdが無いこと。
- 未確認: Slack〜Cloudflare Worker〜rust-worker-sqlx-d1の経路、100秒を超える回答でのCloudflareの打ち切り、`ask_id`照会の経路、実際のコンテナ再起動後の復元、`workspace:`の`/root`以外のパス、stream_routesと本体Workerの台帳（今回は触っていない）。

## 追記: 不具合1・2の修正（2026-11-02）

**対象**: `ops/chat_observer_claude.py`の`send_to_console`・`public_snapshot`、`test/chat_observer_claude_test.py` — 下記の不具合1・2を修正し、修正の確認中に見つかった不具合4も修正した。以下の本文は修正前の評価として残す。

| 不具合 | 修正 | 確認 |
|---|---|---|
| 1. テキストがCLIのオプションになる | 引数を`… --resume <id> -- <text>`にした | 先に失敗するテストを書き、修正後に通過。専用セッションへ`--version …`・`-p --model x …`で始まるテキストを送り、プロンプトとして扱われて返答（`PONG`・`PING2`）が届いた |
| 2. 送信先のCLIがスタブ | `claude_binary()`で`LIB_CHAT_CLAUDE_BIN`→`/opt/claude-web/claude`→npmのネイティブバイナリの順に、実行できる最初のものを選ぶ | 同上（テスト、実際の送信）。このホストではネイティブバイナリが選ばれる |
| 4.（新規）`claude -p`の会話で状態が`active`のまま | 最終回答（`stop_reason: end_turn`）でも`idle`にする | `claude -p`の記録に`turn_duration`が無いことを実際の記録で確認。先に失敗するテストを書き、修正後に通過。実際の送信で`idle`→`active`→`idle`と変わった |

`claude/test`は7件すべてOK。送信テストは、この会話ではなく、送信用に作った専用のセッションで行った。`spec-eval create`は未試験のまま。

## 追記: PLANの段階0の実施（2026-11-02）

**対象**: [`PLAN.claude.20261102.md`](PLAN.claude.20261102.md)の段階0のうち、合意を要しないもの — 下記の「テストの評価」で不足としたものを埋め、`spec-eval create`を確かめた。

| 作業 | 結果 |
|---|---|
| `tunnels.claude.rb`のテスト | `test/tunnels_claude_rb_test.rb` 4件。`--json`、接続数が整数、待ち時間（メッセージ付きは300、投入のみは0）、読み込みでCGIが動かないこと。3つの差し替えを1つずつ外すと、それぞれ失敗することを確認。実行順を12通り変えて通過 |
| 上記に伴う修正 | CGIとして直接実行されたときだけ`run!`する。2回読み込むと待ち時間の差し替えが自分自身を呼ぶ不具合があり、1回だけ差し替えるよう直した（テストの実行順によって表に出た） |
| `llm_worker_claude.py`のテスト | `test/llm_worker_claude_test.py` 5件。helperのbindが`/run`のtmpfsより後、`/root`のtmpfsと作業ディレクトリのbindの順序、`/root`外では何も足さない、codexは変えない。差し替えを外すと失敗することを確認 |
| 手動確認のスクリプト | `test/manual/`に`askgk_request.rb`・`observer_send.py`と手順書`MANUAL_CHECKS.md`を置いた。手順どおりに実行し、askgk（`done`、約6秒）とobserverの送信（`PONG3`、`idle → active → idle`）が再現した |
| `spec-eval create` | 使い捨ての複製リポジトリと送信用のセッションで実行。受付（`pending`）と依頼の送信までは動いた。**EVALは作られなかった**。`claude -p --resume`のセッションには、作業ディレクトリ外の対象リポジトリを読む権限がなく、非対話のため許可も出せない。Claudeはツールが拒否されたことを報告し、評価をしたふりはしなかった。受付記録と複製は削除した |

新たに分かったこと:

- `spec-eval create`をClaudeのobserverで完了させるには、送信時に対象リポジトリの読み書きを許可する必要がある（例: `--add-dir <リポジトリ>`と、書き込みを含む`--allowedTools`）。権限を広げる判断のため、実装していない。PLANの段階5に、決めることとして追加した。
- askgkの回答で、Claudeが「`/root/lib`はコミットがない」と述べた。実際にはコミットがある。sandbox内で`codex-web`から`root`所有のリポジトリを見たときのgitの扱い（所有者の確認）によると思われるが、確かめていない。

## 総合評価

本番の配置がないこのホストで、tunnels API、`/neko askgk claude_prompt=…`の応答、会話observerの表示までは動く。元ファイルを変えない方針も守れている（`git status`で変更は`claude/`のみ）。

一方で、observerの送信（`send`）に不具合が2件ある。この環境では既定の設定で必ず失敗し、送信テキストがCLIのオプションとして解釈される。SPECは送信を「未試験」としか書いておらず、この2件を見落としていた。テストはobserverの表示部分だけで、tunnels API・workerの別名版にはない。

SUGGESTの12件のうち実装済みのものはない。現状は「Codex向けの設計をClaude Codeで動かす」段階で、Claude Code固有の機能は、もとからhelperが使っていた`stream-json`・`dontAsk`・`--allowedTools`以外は使っていない。

| 観点 | 評価 |
|---|---|
| SPECへの適合（表示・応答） | 良い。主要な経路は実際に動かして確認済み |
| SPECへの適合（observerの送信） | 不具合あり（下記の不具合1・2） |
| 元ファイルを変えない方針 | 守れている |
| テスト | 不足。observerの表示部分のみ |
| 運用（常駐・タイムアウト） | 未整備。SPECの「未対応」に記載のとおり |
| Claude固有の機能の活用（SUGGEST） | 未着手 |

## SPECへの適合

**対象**: SPECの「構成」から「llm_worker_claude.py / claude-helper.sh」までの記述 — 書いてあるとおりに動くかを、実行結果で確かめた。

| SPECの記述 | 確認方法 | 結果 |
|---|---|---|
| tunnels: shebang・`--json`・接続数が整数 | 実行してトンネル一覧と`status=healthy`の絞込を取得 | 適合 |
| tunnels: 共通処理を`../../api/tunnels_lib`から読む | 別ディレクトリから実行 | 適合 |
| tunnels: メッセージ付きの待ちが300秒、`wait 0`は0 | worker通信をスタブにして渡る値を記録（`[300, 0, 300]`） | 適合。実際に300秒かかる応答は未試験 |
| askgk: 署名付きPOSTに応答、署名なしは401 | 実際にworker経由で実行（約6秒で`done`）、署名なしで`401 hmac_required` | 適合 |
| worker: sandbox内の`/root`は作業ディレクトリのみ | askgk経由でClaudeに`pwd; ls -A /root`を実行させた（`/root/lib`、`lib`） | 適合 |
| observer: ソケット・プロトコル・出力の形が元と同じ | `chat_websocket.py`経由の`observe`でこの会話を受信 | 適合 |
| observer: 非公開の内容を出さない | テスト（思考過程・コマンド・出力・meta・サブエージェント） | 適合（テストの範囲で） |
| observer: 状態の判定 | テスト（`turn_duration`で`idle`、途中で`active`） | 適合。ユーザーが中断したターンは未確認（このホストの記録に中断が0件） |
| observer: 送信は`claude -p --resume`で起動 | CLIの挙動とPATHを確認 | **不適合**（不具合1・2） |
| observer: `workspace:`指定で最新の記録を追う | テストは`sessionId`のみ | 未確認。プロジェクトのディレクトリ名の作り方（英数字以外を`-`に置換）は、`/root`→`-root`の1例でしか確かめていない |

## 見つかった不具合

**対象**: `ops/chat_observer_claude.py`ほか — 評価のために実際に確かめて見つかったもの。いずれも未修正。

### 1. 送信テキストがCLIのオプションとして解釈される（重大度: 高）

- 箇所: `send_to_console`が`[CLAUDE, '-p', '--resume', session_id, text]`で起動している。
- 確認: テキストが`--version`のとき、プロンプトとして扱われず`2.1.316 (Claude Code)`を出力して終わった。`--`を前に置くと、プロンプトとして扱われた（存在しないセッションへの`No conversation found`まで進んだ）。
- 影響: 送信できるのはHMACで認証された利用者だけだが、テキストで`--dangerously-skip-permissions`などのオプションを渡せる可能性がある。元の`llm_worker.py`は「プロンプトは標準入力で渡し、CLIのオプションにしない」としており、その方針にも反する。
- 対処案: 引数を`[..., '--resume', session_id, '--', text]`にするか、標準入力で渡す。`-`で始まるテキストのテストを追加する。

### 2. この環境では送信が既定の設定で必ず失敗する（重大度: 中）

- 箇所: `CLAUDE = os.environ.get('LIB_CHAT_CLAUDE_BIN', 'claude')`。
- 確認: PATH上の`claude`は`/opt/node22/bin/claude`で、`claude --version`が`Error: claude native binary not installed.`で終わる。`send`は2秒以内の失敗終了となり、`console_unavailable`を返す。
- 影響: 送信機能はこのホストでは動かない。`claude-helper.sh`には同じ問題への代替経路を入れたが、observerには入れていなかった。
- 対処案: helperと同じ順で実行ファイルを選ぶ（`/opt/claude-web/claude`、次にnpmパッケージのネイティブバイナリ）。

### 3. その他（重大度: 低）

| 箇所 | 内容 | 確認状況 |
|---|---|---|
| observer `public_snapshot` | 1つの記録エントリにテキストが複数あるとメッセージIDが重複する。画面（`chat/app.mjs`）はIDで表示を管理しているため、後のテキストが前を上書きする | このホストの記録では、テキストが複数あるエントリは248件中0件。現状では起きない |
| observer `user_text` | `<`で始まる発言はharnessのタグとみなして表示しない。利用者が`<`で始まる文章（HTMLなど）を入力すると表示されない | 設計上の割り切り。未テスト |
| observer `send_to_console` | `session_cwd`が最大4MiBの記録を同期的に読む。読む間、他の接続の処理が止まる | 未計測 |
| `claude-helper.sh` | 代替のバイナリのパスが、npmパッケージの内部構成に依存する。Claude Codeを更新するとパスが変わる可能性がある | 未確認 |
| `tunnels.claude.rb` | 待ち300秒と、このホストのApacheの`Timeout 300`が同じ値。境界でCGIが打ち切られ得る | SPECの「未対応」に記載済み |
| worker・observer | 元と同じソケットを使うため、元のworker・observerと同時に起動できない | SPECに記載済み。workerのserviceには`Conflicts=`がない（元のunit名が不明なため） |

## テストの評価

**対象**: `lib/claude/test`と、別名版が依存する元のテスト — 何を検証していて、何を検証していないか。

| 対象 | テスト | 検証していないこと |
|---|---|---|
| observer（表示） | `chat_observer_claude_test.py` 4件 | 送信、`workspace:`指定、spec-eval、ソケット越しの`handle` |
| observer（送信） | なし | 不具合1・2は、テストがあれば見つかっていた |
| `tunnels.claude.rb` | なし（手動実行と一時スクリプトで確認） | `--json`の引数、接続数が整数の場合、待ち時間の差し替え |
| `llm_worker_claude.py` | なし（実行して確認） | bwrapの引数（`/root`のtmpfs、helperのbind）の組み立て |
| 元の共通処理 | `llm_prompt`・`tunnels_claude`・`llm_worker`・`chat_observer`・`chat_websocket`（`PYTHONPATH=ops`が必要） | 別名版での差し替えの影響 |

手動の確認は、一時スクリプト（`askgk.rb`、ソケットの接続スクリプト）で行い、リポジトリに残していない。同じ確認を再現できない。

## SUGGESTに対する現状

**対象**: SUGGESTの12件 — 現状の実装がどこまで対応しているか、提案を入れる前に直すべきものはあるか。

| 提案 | 現状 | 評価 |
|---|---|---|
| 1. 応答の逐次配信 | 未対応。workerは最終の`result`だけを使い、キュー経路は`final_answer` | 待ち時間を300秒にしたので必要性が上がった |
| 2. 費用上限 | 未対応。上限は時間（300秒）と出力サイズのみ | 同上 |
| 3. Bashをコマンド単位に絞る | 未対応。`Bash`を全許可 | sandboxで書き込みは防げているが、通信と`cf`の任意実行は可能 |
| 4. 送信を安全にする | 未対応。`--resume`の同時書き込みに加え、不具合1・2がある | **提案より先に不具合1・2を直す必要がある** |
| 5. フックでイベント駆動 | 未対応。1秒ごとの確認 | 現方式は動作している。急ぎではない |
| 6. 会話の継続 | 未対応。`--no-session-persistence` | 合意が必要（tunnels APIとWorkerの変更） |
| 7. 構造化出力 | 未対応 | 用途の決定が先 |
| 8. MCPツール | 未対応。MCPは空 | 3と合わせて検討 |
| 9. 代替モデル | 未対応 | 簡単に入れられるが、モデルの選定が必要 |
| 10. 常駐コンソール | 未対応 | 4・5で足りるなら不要 |
| 11. SPEC評価をサブエージェントで | 未対応。spec-evalは元の方式（会話への送信）で、その送信が不具合1・2の影響を受ける | `create`は現状この環境で動かない |
| 12. `--bare` | 未対応 | OAuthの認証では使えない。現状のままが妥当 |

## 推奨する対応の順

1. 不具合1（オプションとして解釈される）を直し、`-`で始まるテキストのテストを足す。
2. 不具合2（送信先のCLI）を直し、送信と`spec-eval create`を実際に試す。送信先は、人が操作していない専用のセッションにする。
3. `tunnels.claude.rb`と`llm_worker_claude.py`の差し替え部分にテストを足す（`--json`、接続数、待ち時間、bwrapの引数）。手動確認に使った一時スクリプトを、テストか手順書として残す。
4. SUGGESTの2（費用上限）と3（Bashを絞る）を、ユーザーの合意を得て入れる。300秒の待ちと組み合わせたときの安全側の対策になる。
5. 常駐化（`entrypoint.sh`）、本番のaskgk待ち時間、Apacheのタイムアウトは、SPECの「未対応」のとおり、反映先の担当者の判断で行う。

## 確認したこと・していないこと

- 確認: この文書の「確認」「結果」に書いたものは、2026-11-01〜02にこのホストで実行して確かめた。不具合1・2は、評価のために2026-11-02に実行して確かめた。テストは`claude/test`の4件がOK（2026-11-02に再実行）。
- 未確認: 実際に300秒かかるaskgk、Slack〜Cloudflare Worker〜rust-worker-sqlx-d1の経路、`ask_id`の照会、observerの送信の成功、中断したターンの状態、`workspace:`指定、本番の`/opt/claude-web/claude`の版。
