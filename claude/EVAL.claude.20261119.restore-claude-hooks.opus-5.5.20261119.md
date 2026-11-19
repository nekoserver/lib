# 評価: コンテナ起動後のフックの復元（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.claude.20261119.restore-claude-hooks.md`](SPEC.claude.20261119.restore-claude-hooks.md)（2026-11-19の改訂版、SHA256 `56ee77f8100028c8d16c1b399759eccde5dcaf2cc6f28253468f56e6046bd032`）
評価対象: libの`main`（`592f438`、PR #161のマージ後）の`claude/ops/restore-claude-hooks.sh`と、本体のdemoコンテナでの実行
区分: [`../SPEC.lib.20261119.spec-eval-refresh.md`](../SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった）

注意: SPEC・実装・この評価は、同じモデル（opus-5.5）が同じ日に行った。自分の作ったものの評価なので、根拠は実測とテストの結果に限った。

---

## 総合

6つの要件をすべて満たす。実際の`~/.claude/settings.json`への書き込みと、書いたガードが同じセッションで働くことを確かめた。

---

## 要件ごとの評価

| 要件 | 判定 | 根拠 |
|---|---|---|
| REQ-RHK-1 | 充足 | テスト2件（自分自身を指すsymlinkを作り直す、正常なら`npm ci`しない）。起動時のログに「node_modules rebuilt with npm ci」 |
| REQ-RHK-2 | 充足 | テスト2件（各スクリプトのOK、欠けた・壊れたスクリプトでNGと失敗）。実行で`hooks: OK`5件 |
| REQ-RHK-3 | 充足 | 実行後の`~/.claude/settings.json`: `PreToolUse`（`Bash`）に全体テストのガード、`UserPromptSubmit`・`SessionStart`に日本語・自己確認、`Stop`に日本語。どれも`node "/root/cloudflare-workers-github-oauth-1/scripts/…"`。pushのガード・マイグレーションの検査は無い |
| REQ-RHK-4 | 充足 | テスト（2回の実行で重複しない、`theme`とほかのフックが残る）。実物でも`theme: auto`が残った |
| REQ-RHK-5 | 充足 | 実行で`hooks: works: the full test guard stops`。さらに同じセッションで、空のディレクトリからの`npx vitest run`を全体テストのガードが止めた（`PreToolUse:Bash hook error: [full-test-guard] 全体テスト(npx vitest run)を止めました`）。止めないガードで失敗することはテスト |
| REQ-RHK-6 | 充足 | 足した変数は無い（`$HOME`と、既存の第1引数だけ） |

`claude/test`のPython 96件はすべて通過（この中にフックの復元のテスト13件）。

---

## 提案（未実施）

1. 自己確認のガードの効き目を、指示が差し込まれたことより先まで確かめる方法は無い（指示に従うかはモデル次第）。確かめる対象から外すことをSPECに書く。

---

## 確かめていないこと

- コンテナの作り直しの直後、entrypointからの実行で`hooks: works`まで出ること（次の起動で確かめられる）。
- `codex-web`ユーザーのClaude Code（`CLAUDE_CONFIG_DIR`が別）。
