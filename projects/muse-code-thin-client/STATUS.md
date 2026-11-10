# 専用シンクライアント Worker の作業記録

このディレクトリは `nekoserver/lib` リポジトリ内の独立した試作プロジェクト。永続的な判断記録・ソース・再現手順はここへ保存する。`/tmp`、`/root/.local/state`、他の管理外ディレクトリの存在は再開の前提にしない。

## 確定した範囲

- 利用者の目的: 現稼働 Worker から必要機能を移植し、既存の対象機能の代替になり得る薄いクライアントを作る。
- 初期構成: Worker / DO の受付・認証・Tailscale WASM POST → 受信側 Muse Code SDK。SDK / CLI / workspace は Worker 内へ移さない。
- フレームワークは案のみ。初期試作に新しいフレームワークを追加しない。
- 初期の同時実行は1、単発の完了確認を先行。常駐セッション・他エンジン・ブラウザ WASM は初期成立の必須条件にしない。
- 既存本番の切替・停止は行わない。秘密値は記録しない。自動 fallback と結果不明時の無条件再送は行わない。

## 取得済みの根拠

Cloudflare の読取 API で現稼働 Worker `cloudflare-workers-github-oauth-1` を確認した。

- 配備版: `f873a68a-201b-4d7a-9203-45f03dcded8d`、100%。配備日時: `2026-11-09T22:52:20.586017Z`。
- `TAILSCALE_WASM` / `AICHAT_JOB` binding が存在。古い文書の「未配備」を現在の事実として扱わない。
- `/content/v2` の配布ソースマップから必要なソースを抽出した。元ソースとハッシュは `migration/provenance.json` / `migration/source/` に保存済み。
- 配布済み `@ai-ecoverse/wasm-tailscale 1.104.1-13` の WASM は稼働版と SHA-256 一致。Go glue も稼働版ソースマップの内容と一致した。
- ローカルの元リポジトリは他の変更を含むため、単にその作業ツリーをコピーせず、稼働版の抽出ソースを移植元とする。

## 今の工程

最新の利用者指定「まずはどういう段取りで進めるかだけ協議」により、実装作業をここで止め、段取りの協議へ範囲を絞った。未完成の試作は削除せず保存する。

保存済み試作は `src/transport.ts`、`src/tailnet.ts`、`src/jobs.ts` 等。通信契約の Node テスト6件は成功したが、Worker の入口・SDK 受信側は未完成で、DO の動作・型検査・実 WASM 起動はまだ未検証。これを動作する専用 Worker として扱わない。既存本番の変更・配備・認証済み SDK 実行は行っていない。

段取りに絞った Muse への最新依頼は `coordination/next-steps-request.md`、送信状態は `coordination/next-steps-status.json` に保存する。応答が得られた場合は `coordination/next-steps-response.md` に保存する。これらの記録はリポジトリ外の一時ファイルに依存しない。

## 未完了を絞る

1. 専用の小さい bundle で実 WASM が起動することを確認する。過去の全体 bundle の `os.Getpid` panic は、今回の試作で再現・解消を確かめるまで原因を断定しない。
2. SDK 受信 API の実在・認証・profile 適用を確認し、専用 POST 契約とつなぐ。
3. 実 WASM → 実 SDK の単発正常終端と、隔離領域での小編集・確認を取得する。

Muse への既存依頼は応答タイムアウトで結果不明。新規の重複作成依頼を繰り返さず、こちらで進められる移植・検証を行う。

## 再開時

このファイルと `migration/provenance.json`、プロジェクトのテストを確認する。依存は `package.json` に記録し、開発環境の `node_modules` は一時的なリンクなので再準備可能にする。詳細な協議経緯はリポジトリ直下の `PLAN.lib.20261110.agent-sessions.md` / `REPORT.lib.20261110.muse-code-sdk.md`。
