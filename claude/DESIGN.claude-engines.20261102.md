# tunnels APIのCodexとClaudeの問い合わせ先をどこまで分けるか

作成日: 2026-11-02
状態: 方針メモ。今はCodexでの利用を前提とし、細かくは分けない（利用者の判断）。下の「分ける条件」に当たったら見直す。

**対象**: `api/tunnels.rb`・`api/tunnels_lib.rb`・`api/llm_prompt.rb`と、その別名版`claude/api/tunnels.claude.rb`、LLM worker — 1つの入口で2つのエンジンを扱う今の形を続けるか、エンジンごとに分けるか。

## 今の形

- 入口は1つ。`message`の先頭`codex_prompt=`／`claude_prompt=`（綴り違いの`_prmpt`・`_promt`も可）で選ぶ。両方あると`codex_and_claude_both_given`。先頭なしの`message`は参謀（`ask_sanbo.rb`）。`default_engine`を指定した入口ではそのエンジン。
- `api/tunnels-claude.rb`は`default_engine: :claude`で、先頭なしをClaudeに向ける入口。共通処理は同じ。
- workerは1つ（`/run/lib-codex/worker.sock`）で両エンジンを扱い、ジョブ保存も共通。`ask_id`に`codex-`／`claude-`が付くため、照会はエンジンを指定しなくても正しいジョブに届く。
- 署名・IP許可・フィルタ・応答の形・`ask_id`照会は共通（`tunnels_lib.rb`）。

## このコンテナ（cf-container）での状況（2026-11-02確認）

- `/lib/api/tunnels`は`tunnels.claude.rb`が応える（`ops/restore-claude-host.sh`）。
- Codex本体`/opt/codex-web/bin/codex`が無い。`codex_prompt="hello"`は`ask_status: failed`、`ask_error: codex_execution_failed`。
- 先頭なしの`message`（例: `/neko askgk 質問`）は、元では参謀（`ask_sanbo.rb`）に行き、`/var/lib/lib-api/ask`が無く例外で落ちていた。2026-11-02からClaudeへ送る（方針の1）。
- エンジンごとの差はすでにある: LLMの待ちはClaude別名版で300秒、元は90秒。

## 方針

分けないもの:

- 共通処理（署名、IP許可、フィルタ、応答の形、照会）。二重に持つと片方の直し漏れが起きる。別名版は元を読み込み、違う箇所だけ差し替える今の作りを続ける。
- このホストのソケット・worker。事実上Claude専用で、分けても得るものが少ない。

必要になったら分けるもの（未実施）:

1. ~~このホストの先頭なし`message`をClaudeへ~~: 2026-11-02に実施（`default_engine: :claude`）。元の振り先は参謀（`ask_sanbo.rb`）で、このホストでは例外で落ちていた。
2. 使えないエンジンを手前で断る: このホストで`codex_prompt=`が来たら、workerに投げる前に「このホストではCodexを扱わない」と分かるエラーを返す。今の`codex_execution_failed`では、故障か未導入かを区別できない。
3. 振り分けは呼出し側で: エンジンごとの送り先（Codex→本番ホスト、Claude→このコンテナ）はCloudflare Worker側で決める。Worker側の今の振り分けは未確認（コードがこのリポジトリに無い）。

1・2は`claude/api/tunnels.claude.rb`だけで済み、元ファイルは変えない。

## 分ける条件

次のように両者の性質が離れたら、URL・workerを含めて分けることを検討する。

- 待ち時間の差が広がる（今: Claude 300秒、Codex 90秒）。
- 費用の上限、許可するツール（Bashの絞り込み）、認証がエンジンごとに違ってくる。PLANの段階2はClaude側だけの変更で、分かれ目になりやすい。
- 片方の障害や混雑が、もう片方の応答を遅らせる（workerのキュー共有）。

## 確認したこと・していないこと

- 確認: 上記のエンジン選択のコード、このコンテナで`codex_prompt=`が`codex_execution_failed`になること（2026-11-02）。
- 未確認: Cloudflare Worker側の振り分け、本番ホストでの`claude_prompt=`の動作、workerのキュー共有による実際の遅れ。
