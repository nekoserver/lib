# PR preparation: 2026-11-05

## Changes

同一会話のwriter競合時にnative thread/queue/addへ一度だけ投稿する。キューの応答内容を検証し、accepted/queuedをHTTPと画面へ伝える。observerは読み取り専用を維持する。バージョン付き画面アセットも更新。

## Validation

- Python: `python3 -m unittest discover -s test -p '*_test.py'` — 89 passed.
- Node: `node --test test/*.mjs` — 42 passed, 2 failed. Existing cookie session tests fail with `location is not defined`; unchanged origin/main reproduces both failures.
- Ruby: test/llm_prompt_test.rb 16 passed; test/railway_exec_test.rb 5 passed; test/tunnels_claude_test.rb 6 passed. test/hmac_auth_env_test.rb cannot load minitest/mock; unchanged origin/main reproduces the same dependency failure.
- Versioned app asset body matches chat/app.mjs; hashed imports differ intentionally. SHA256 filename prefix verified.
- Logs: artifacts/pr-20261105/. No live prompt was submitted in PR preparation.

## Boundaries

ドラフトとして公開。実ブラウザ・コンテナ再作成後の復元・切断後の手動再送の重複排除は未検証。本体PR https://github.com/nekoserver/cloudflare-workers-github-oauth-1/pull/2521 のLIB_NETWORK_REVISIONは、採用する公開済み固定コミットの指定が別途必要。ビルド・デプロイは実施しない。
