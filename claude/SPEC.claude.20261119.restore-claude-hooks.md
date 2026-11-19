# SPEC: コンテナ起動後のClaude Codeのフックの復元（2026-11-19）

作成日: 2026-11-19（UTC）
作成: opus-5.5（Claude Opus 5.5、Claude Code）
対象: [`claude/ops/restore-claude-hooks.sh`](ops/restore-claude-hooks.sh)（[`restore-claude-host.sh`](ops/restore-claude-host.sh)の最後の段から呼ぶ）
関連: [`SPEC.claude.20261118.restore-claude-host.md`](SPEC.claude.20261118.restore-claude-host.md)（復元の全体）、本体の`AGENT.md`14〜18行（このコンテナでは全体テストを実行しない、ユーザー指定 2026-11-06）、本体の`NOTICE.cloudflare-workers-github-oauth-1.20261114.hook-test-limits.md`（全体テストのガードの限界、案C）

---

## 1. 起きていたこと

**対象**: 2026-11-19に、フックの「復元」が成功と出たのに、フックが1つも効いていなかった件。

| 項目 | 内容 |
|---|---|
| 起きたこと | `/root`で始めたClaude Codeのセッションが、本体リポジトリで全体テスト（`npx vitest run`）を走らせた。本体の`AGENT.md`は、このコンテナでの全体テストを禁じている |
| 止まらなかった理由 | 止めるはずの`scripts/claude-full-test-guard.js`は、本体の`.claude/settings.json`にしか登録されていない。Claude Codeはセッションを始めたディレクトリの`.claude/settings.json`しか読まないため、`/root`で始めたセッションには本体のフックが1つも無かった。ユーザーの設定（`~/.claude/settings.json`）は`{"theme":"auto"}`だけだった |
| 復元が見落とした理由 | `restore-claude-hooks.sh`は、`node_modules`を直すことと、フックのスクリプトがあって`node --check`を通ることしか確かめていなかった。5本すべてに`hooks: OK`と出たが、フックが効いているかどうかは確かめていなかった |
| `~/.claude`が残らない | コンテナを起動し直すと、`~/.claude/settings.json`は作り直される。手で登録しても、次の起動で消える |

---

## 2. 復元が行うこと

**対象**: コンテナを起動した後、本体のentrypointが`restore-claude-host.sh`を呼び、その最後の段が`restore-claude-hooks.sh`を呼ぶ。そこで行う処理。

| 段 | 処理 | 失敗したとき |
|---|---|---|
| 1 | 本体の`node_modules`が無いか、自分自身を指すsymlinkなら、`npm ci`で作り直す（push のガードの`npx vitest`が読み込めるように） | `hooks: npm ci failed`、終了コード1 |
| 2 | 本体の`.claude/settings.json`にあるフックのスクリプトを、すべて「ある・`node --check`を通る」で確かめる | `hooks: NG scripts/…`、終了コード1 |
| 3 | どのディレクトリでも働くガード（下の表）を、**絶対パス**で`~/.claude/settings.json`に書き込む。段2を通ったものだけを入れる | 入らなかったガードは書かない |
| 4 | **実際に効くかを確かめる**。書き込んだ全体テストのガードのコマンドを、リポジトリの外（`/`）から、Claude Codeと同じ形の入力で動かす。`npx vitest run`を終了コード2で止め、`git status`を通せば`hooks: works: …` | `hooks: NG …`、終了コード1 |

`restore-claude-host.sh`は、この失敗を報告するだけで、前の段（Apache・常駐プロセス）は戻さない。ログは`/tmp/restore-claude-host.log`。

### 2.1 ユーザーの設定に入れるフック

| フック | 契機 | 入れる理由 |
|---|---|---|
| `claude-full-test-guard.js` | `PreToolUse`（`Bash`） | コマンドの文字列だけで判定する。どのディレクトリでも同じに働く |
| `claude-japanese-guard.js` | `UserPromptSubmit`・`SessionStart`・`Stop` | 日本語で答えさせる（ユーザー指定 2026-11-11）。リポジトリに依存しない |
| `claude-self-check-guard.js` | `UserPromptSubmit`・`SessionStart` | 指示を差し込むだけ。リポジトリに依存しない |

### 2.2 入れないフック

| フック | 入れない理由 |
|---|---|
| `claude-push-guard.js` | 自分の作業ディレクトリで`git diff origin/main...HEAD`を走らせる。`/root`のセッションでは、どのリポジトリへのpushかが分からない |
| `check-migration-table-registry.js` | `Edit`・`Write`のたびに本体のWorkerへ記録を送る。本体以外の編集でも送ってしまう |

### 2.3 書き込みの決まり

- 契機・`matcher`・`timeout`などは本体の`.claude/settings.json`のとおりにし、コマンドだけを`node "<本体の絶対パス>/scripts/<名前>"`に書き換える。
- 前回の実行で入れた行（`node "/…/scripts/<上の3つの名前>"`の形）は消してから入れ直す。何度実行しても重複しない。
- ユーザーの設定にあるほかの項目・ほかのフックは残す。
- 一時ファイルに書いてから置き換える（書きかけの設定を残さない）。
- 新しい環境変数・設定スイッチは足していない。置き場所は`$HOME/.claude/settings.json`、本体の場所は今までどおりスクリプトの第1引数（既定`/root/cloudflare-workers-github-oauth-1`）。

---

## 3. 確かめたこと

| 項目 | 方法 | 結果 |
|---|---|---|
| テスト | `python3 -m unittest restore_claude_hooks_test restore_claude_host_test`（`claude/test/`）。新しいテスト（`UserLevelHooksTest`）は、実装の前に書いて落ちることを確かめた | 28件すべて通過 |
| 実物（2026-11-19） | このコンテナで`sh claude/ops/restore-claude-hooks.sh`を実行 | `hooks: OK`5件、`hooks: user level /root/.claude/settings.json: 6 hooks`、`hooks: works: the full test guard stops \`npx vitest run\` outside the repo`、終了コード0 |

テストの中身:

| テスト | 確かめること |
|---|---|
| `test_installs_the_directory_independent_guards_with_absolute_paths` | 3つのガードが、本体と同じ契機・`matcher`で、絶対パスで入る |
| `test_leaves_out_the_hooks_that_need_the_repo_as_working_directory` | pushのガードとマイグレーションの検査は入らない |
| `test_keeps_other_settings_and_hooks_and_does_not_duplicate` | ほかの設定・フックが残り、2回実行しても重複しない |
| `test_a_broken_guard_is_not_installed` | 構文の壊れたガードは入らず、終了コードが0でない |
| `test_checks_that_the_installed_full_test_guard_really_blocks` | 入れたコマンドを動かし、`npx vitest run`が止まることを確かめる |
| `test_a_guard_that_does_not_block_fails` | 止めないガードなら`hooks: NG`で失敗する |
| 既存の6件 | `node_modules`の作り直し・スクリプトの確認（一時の`HOME`で動かし、本物の`~/.claude`に書かない） |

---

## 4. カバーしていないこと

| 項目 | 内容 |
|---|---|
| 動いているセッション | 復元より前に始まったセッションに、新しいフックが読み込まれるかは確かめていない。確実にするには、セッションを始め直す |
| 本体で始めたセッション | 本体の設定とユーザーの設定の両方から、同じガードが2回動く。ガードは止めるか指示を出すだけなので、結果は変わらない（日本語の指示が2回入る） |
| pushのガード | `/root`で始めたセッションでは動かない。本体の`AGENT.md`・CLAUDE.mdのpushの前の手順は、エージェントが自分で守る必要がある |
| 別のユーザーのClaude Code | `codex-web`ユーザー（`CLAUDE_CONFIG_DIR=/var/lib/codex-web/.claude`）など、rootの`~/.claude`を使わないものには入らない |
| 日本語・自己確認のガードの実際の効き目 | 全体テストのガードだけを実際に動かして確かめた。ほかの2つは段2（スクリプトの有無と構文）だけ |
| コンテナの作り直しの直後 | 起動済みのコンテナで手で実行して確かめた。作り直した直後のentrypointからの実行は、2026-11-19の時点で確かめていない |
| 案Cとの違い | 本体NOTICEの案Cは「`cwd`のgitルート→カーネル名で、このコンテナのときだけ効かせる」判定を求めている。ここではその判定を入れていない。ユーザーの設定はこのコンテナの`~/.claude`にしか書かず、Web版のエージェントには届かないため |
