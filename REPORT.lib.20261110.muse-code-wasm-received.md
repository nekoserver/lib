# Muse 側の専用 Worker 作成結果（利用者からの共有）

2026-11-10 UTC、利用者から Muse 側の作成結果が共有された。以下はその報告内容であり、このホストでソース・実機・検証ログを独立確認した結果ではない。

## 報告された成果

- 新規プロジェクト: Muse 側の `~/workspace/muse-code-wasm/`。Worker 名 `muse-code-wasm`。
- `CodeGateway` Durable Object が Tailscale WASM ノードを保持し、tailnet 経由で受信 API へ POST。WASM パッケージ `1.104.1-13` は integrity 検証済みとのこと。
- 受信 API は Muse VM の `:8090` を想定し、SDK で1ターン実行。既定 `:auto-review`、`:unrestricted` への fallback なし、指示8000文字まで、要求ごとに workspace を隔離。
- 応答前に結果を保存し、再読み可能とのこと。
- プロファイル一覧と host 既定 `:ask-me` を実地確認。受信 API のローカル9テスト、Worker の `tsc --strict`、`wrangler deploy --dry-run`（約29.9 MiB）が成功したとのこと。
- 詳細は同プロジェクトの `README.md` / `PROGRESS.md` に保存済み。

## 未確認とされた点

1. `:auto-review` の認証済み実ターン。この host では reviewer が利用できず現状拒否される。`META_API_KEY` 設定後も、その設定だけで解消したとはせず再確認が必要。
2. Worker 実機での WASM ノード動作と、受信 API `:8090` への tailnet 到達。
3. 専用 Worker の配備と秘密設定。Worker 側の `TS_AUTHKEY` / `RECEIVER_API_KEY` / `WORKER_API_KEY`、受信側の `MUSE_CODE_WASM_API_KEY` / `META_API_KEY` が必要と報告された。値は記録しない。

dry-run の bundle 成功と実機上限・動作成立は別である。リリース版の配布サイズ、受信 API 契約、実効 profile、結果保存と重複抑止、既存稼働 Worker からの移植対応は、ソースとログを取得してから照合する。

## 今後の扱い

この作成結果を以後の実装候補に一本化する。`projects/muse-code-thin-client/` のこちらの試作は未完成の先行記録として残し、競合する別の完成版を作り進めない。利用者の最新方針である「まず段取りを協議」を維持する。

PR 整備のため、Muse に絶対パス・git 管理・認証値を除いた origin / branch / commit・push / PR 状態だけを読取で問い合わせた。作成依頼の再送や、秘密設定・新規公開の依頼ではない。回答は同試作下の `coordination/muse-implementation/` に保存する。
