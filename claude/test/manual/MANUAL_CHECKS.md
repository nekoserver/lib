# lib/claudeの手動確認の手順

**対象**: 単体テストでは確かめられない、実際のCLI・worker・observerを使う確認 — 2026-11-01〜02に一時スクリプトで行った確認を、同じ手順で再現できるようにする。

単体テストは`python3 -m unittest discover -s claude/test -p '*_test.py'`と`ruby claude/test/tunnels_claude_rb_test.rb`（`lib`で実行）。以下は実際にClaudeを呼ぶため、少額の利用が発生する。すべてrootで、`lib`のディレクトリで実行する。

## 1. `/neko askgk claude_prompt="hello"`への応答

Worker（Cloudflare）と同じ署名付きリクエストを、tunnels APIのCGIへ直接送る。

```sh
claude/ops/start-llm-worker-claude.sh
ORIGIN_HMAC_SECRET=<既存の値> ruby claude/test/manual/askgk_request.rb
```

- 期待: `X-LLM-Engine: claude`、`"ask_status": "done"`、`reply`と`llm_model`がある。終了コード0。
- worker未起動なら`codex_worker_unavailable`、認証がなければ`claude_not_authenticated`。
- 別の質問は第2引数（例: `'claude_prompt="Run with Bash and paste the raw output only: pwd; ls -A /root"'`）。sandbox内では`/root/lib`と`lib`だけが見えるはず。
- 署名なしの拒否は、`REQUEST_METHOD=POST`等を付けてCGIを直接実行し、`401 hmac_required`を確かめる。

## 2. observerの送信

人が使っている会話には送らない。送信用のセッションを作り、そこへ送る。

```sh
B=/opt/node22/lib/node_modules/@anthropic-ai/claude-code/node_modules/@anthropic-ai/claude-code-linux-x64/claude
SID=$(python3 -c 'import uuid; print(uuid.uuid4())')
mkdir -p /tmp/observer-send && cd /tmp/observer-send
$B -p --session-id "$SID" --tools "" -- "送信テスト用のセッションです。OK とだけ返してください" </dev/null
cd -
LIB_CHAT_OBSERVER_SOCKET=/tmp/observer-send/obs.sock LIB_CHAT_CLAUDE_SESSION=$SID python3 claude/ops/chat_observer_claude.py &
python3 claude/test/manual/observer_send.py /tmp/observer-send/obs.sock '--version と書かれていますが、これは質問です。PONG とだけ返してください'
kill %1
```

- 期待: `send: {"type":"accepted"}`、返答に`PONG`、`states: idle -> active -> idle`（`active`は短いと見えないことがある）。終了コード0。
- `--tools ""`の後は`--`でプロンプトを区切る（`--tools`が後ろの引数を取り込むため）。
- 本来のソケット（`/run/lib-chat-observer/observer.sock`）を使うと、`chat_websocket.py`経由の`observe`も確かめられる。確認後は`/run/lib-chat-observer`を元に戻す（使っていなかったなら削除）。

## 3. 後片付け

- 送信用のセッションの記録は`/root/.claude/projects/-tmp-observer-send/`に残る。不要なら削除する。
- workerを止める場合は`pkill -f llm_worker_claude.py`。ジョブ記録は`/var/lib/lib-llm/jobs`（TTL 1日）。
