# Muse Code SDK の導入状況・変更点・今後の計画

確認日: 2026-11-10 UTC。利用者の依頼により、Muse（`muse-vm:8080`）へ導入状況、設定、変更履歴、検証範囲を問い合わせた。

## 根拠と確認範囲

- **このホストからの実測**: Tailscale の `muse-vm` は online、`GET /health` は HTTP 200 / `{"status":"ok"}`。Bearer 認証付き `POST /v1/chat/completions` による今回の問い合わせも HTTP 200 で回答を取得した。
- **パッケージ一覧の実測**: `GET /nix/packages` の `generatedAt: 2026-11-10T00:29:58Z` の一覧に `muse-api-bridge 0.4.0`、`nix 2.35.4`、`tailscale 1.104.5` が含まれる。Nix の一覧だけでは pip / npm / venv の SDK 導入状況は判定できない。
- **Muse の調査報告**: 以下の CLI・SDK・別プロジェクトの情報は、Muse が対象 VM のファイル・記録を確認したとする回答に基づく。このホストからリモートファイルを直接検査した結果とは区別する。
- GitHub 接続から `neko0707/muse-code-test-` の内容取得を試みたが 404 だった。権限不足と未存在は区別できず、リポジトリ不存在の証拠にはしない。push・Cloudflare 配備状況は独立確認できていない。
- **公開一次資料の確認**: [Muse Code SDK README](https://github.com/meta-models/muse-code-sdk/blob/main/README.md) を GitHub 接続で取得した。TypeScript の `@muse-code/sdk`、Node.js 20 以上、CLI と SDK の同版対応、正確な版の固定、Developer Preview、MIT ライセンスを確認できた。この README だけでは Python パッケージの配布元・API 契約は確認できないため、Python 側は Muse の報告として扱う。

## 導入状況と既存 API との関係

| 対象 | 確認内容 | 根拠・制約 |
| --- | --- | --- |
| Muse API bridge | `muse-vm:8080` が今回の問い合わせに応答 | このホストから実測。Muse Code SDK の成功を意味しない |
| Muse Code CLI | `Muse Code 1.4.14 (1.4.14-R7309.1)` | Muse の `muse --version` 調査報告 |
| CLI 配置先 | `~/.local/bin/muse`、実体 `~/.local/bin/muse-bin-1.4.14-R7309.1` | `~` は Muse VM 側。実体は約 415 MB と報告 |
| Python SDK | 配布名 `muse-code-sdk`、import 名 `muse_code` | Muse は追加調査で標準 Python 3.12.3 の `find_spec("muse_code")=None`、配布メタデータも不存在と報告。専用環境・過去の試験環境は未特定 |
| TypeScript SDK | `@muse-code/sdk` | Muse の報告。`require.resolve` で見つからず、global npm 一覧は空 |
| 検証用プロジェクト | `~/workspace/kernel/muse-code-test/` | Muse VM 側の別プロジェクト。このホストの `musevm` / `musevm-kernel` と混同しない |
| コンテナでの SDK 導入 | CLI の `X.Y.Z` に合わせて `muse-code-sdk==X.Y.Z` を導入する設計 | CLI 1.4.14 なら SDK 1.4.14。イメージ完成・配備成功の確認ではない |

現在の `lib/claude/ops/llm_worker_claude.py` は `muse_prompt` を OpenAI 互換 API に転送する。Muse Code SDK を起動する実装ではない。一方、Muse の説明する検証用プロジェクトは `POST /cf-containers/code` → `POST /agent/code/run` → Python SDK → `muse serve` という別経路である。

検証用プロジェクトの既定値として、ワークスペース `~/muse-code-workspace`、権限プロファイル `:unrestricted`（`MUSE_CODE_PERMISSION_PROFILE` で変更可）、タイムアウト 1200 秒（`MUSE_CODE_TIMEOUT`）、要求ごとの単発セッションが報告された。継続・レジュームは未対応とされる。これらは現時点では Muse の説明であり、本番の稼働設定として確認した値ではない。

## 最近の変更点（Muse からの報告）

| 日時 | 変更前 → 変更後 | 根拠として挙げられたもの |
| --- | --- | --- |
| 2026-11-09 20:46 UTC | Muse Code CLI なし → 1.4.14 導入、`.bashrc` / `.profile` に PATH 追加 | CLI ファイル時刻、各 shell 設定、Muse VM の `MEMORY.md` / `memory/2026-11-10.md` |
| 2026-11-10 と記録 | `musevm-kernel` 系の複製 → `muse-code-test` に CLI・SDK 導入、コード実行 API、制御画面を追加 | `Dockerfile`、`container-agent.py`、`src/index.ts`、`README.md` |
| 同上 | Worker→コンテナの環境変数転送に `META_API_KEY` を追加 | Muse が確認した実装。キーの値は記録しない |
| 同上 | TypeScript の厳密検査設定を追加 | `tsconfig.json`、TypeScript 7.0.2 の `tsc --strict` 成功との記録 |
| 同上 | `neko0707/muse-code-test-` に 31 ファイルを push、最終 SHA は `2d13dfcf67fc138433bfcd9eb0a7c8586178e943` と報告 | Muse の記録。GitHub 側は未確認 |

Muse は CLI ランチャーに既定 3600 秒間隔の更新確認があり、今回の `muse --version` 調査に伴って `.muse-update-checked-at` / `.muse-release-info.json` が 2026-11-10 00:29 UTC に更新された形跡も報告した。バージョン変更はないとのこと。以後の追加調査では、自動更新を誘発し得る CLI 呼び出しを避けるよう依頼した。

## 認証・検証結果・残る確認

- Muse の説明では、対話認証は OIDC デバイスコード、ヘッドレス認証は `META_API_KEY`。このホストが bridge 接続に使う `MUSE_API_KEY` と名前・用途が異なる。秘密値を転記しない。
- Muse VM の `~/.config/muse/` が存在しないとの報告がある。ただし、それだけで `META_API_KEY` による認証も不可とは判断しない。
- 過去の SDK スモークでは、セッション開始とターン送信後に `terminal=failed` / `authRequired` を受信したとの記録。これは正常な回答生成・ツール実行・ファイル編集の成功ではない。
- SDK の `clientInfo.name` が `^[a-z0-9_]+$` を満たす必要があり、実装を修正したと報告された。
- `tsc --strict`、ページ内 JavaScript 構文検査、`container-agent.py` の `py_compile` 成功は Muse の記録による。今回このホストで再実行していない。
- 過去に SDK 1.4.14 で試験したとの記録と、現在の標準環境で SDK が見つからない点は両立し得る。専用 venv 等の配置先を追加確認する。
- Cloudflare の Worker 作成・Builds 接続・`META_API_KEY` 設定は利用者が実施済みと Muse が記録しているが、初回ビルド結果、配備済みバージョン、認証済み実ターンは未確認。
- GitHub リポジトリ名 `muse-code-test-` と Worker 名 `muse-code-test` の違い自体は障害と断定しない。実際の Builds 接続先・ビルドルート・デプロイ先の対応を確認する。

## 追加質問で訂正・明確化した点

Muse へ、専用環境、認証、時刻、実装抜粋について追加質問し、HTTP 200 の回答を得た。

- 「VM に SDK が未インストール」とは断定しない、と Muse も訂正した。標準 Python のパッケージ照会で見つからず、uv / pipx / venv も見つからなかったとの報告だが、以前のスモーク環境の所在は依然未確認。
- agent は `from muse_code import (MuseClient, …)`、`MuseClient.spawn(...)` を使うとの追加報告。初回の `import muse_code_sdk` は誤りと Muse が訂正し、正しい名前での不在確認結果を回答した。TypeScript SDK はこの実装では未使用とのこと。
- Muse VM の環境変数には `META_API_KEY` がないとの報告。Cloudflare Worker / 実行コンテナのキー状態は別に確認する必要がある。
- 利用者による Cloudflare 設定済み報告の「2026-11-10 06:26 頃」は **JST**（2026-11-09 21:26 UTC）と明確化された。初回回答の時刻を UTC として解釈しない。
- 初回以降は `muse --version` を再実行せず、バージョン付きバイナリの存在だけを確認したとのこと。SDK・CLI の更新は依頼していない。

### 公開配布情報との照合

このホストから [PyPI の公式配布メタデータ](https://pypi.org/pypi/muse-code-sdk/json) を直接取得し、`muse-code-sdk 1.4.14` の公開を確認した。必要 Python は `>=3.10`、依存は `muse-code-msp==1.4.14` と `pydantic==2.13.5`。Muse の「1.4.12 までしか確認できない」という回答は、現在の公開版の上限としては採用しない。公開済みであることと、対象 VM / コンテナへのインストール成功は別である。

配布説明の import は `from muse_code import ...`。起動例は `await MuseClient.spawn(MuseClientSpawnOptions(muse_bin="muse", args=["serve"]))` である。Muse が要約した引数直渡し形式と同一とは限らないため、実装時は 1.4.14 の実際のシグネチャ・オプション型との一致を確認する。

### 対象ファイルを指定した再照会

計画協議中に Muse が「Dockerfile / agent に SDK 組込みもなし」と回答し、初回報告と矛盾したため、対象の絶対パスと行番号を指定して再調査を依頼した。Muse は後の「組込みなし」を撤回し、以下を確認したと回答した。

- `/home/hatch/workspace/kernel/muse-code-test/Dockerfile` 124〜136 行: CLI インストーラと SDK の CLI 同版導入。
- `/home/hatch/workspace/kernel/muse-code-test/container-agent.py` 232〜240 行: `muse_code` の import と `await MuseClient.spawn(MuseClientSpawnOptions(...))`。実装はオプション型を渡す形式で、先の略記を実コードと解釈しない。
- `/home/hatch/workspace/kernel/muse-code-test/src/index.ts` 430〜447 行: `/cf-containers/code` → `/agent/code/run` の停止ゲート付き転送。
- 過去の SDK 1.4.14 スモークの根拠は `memory/2026-11-10.md` の記述であり、今回実行して得たログではない。

これは Muse によるリモートファイルの再確認報告である。配備済みイメージに同じコードがあることは、引き続き段階1で照合する。

## Muse と協議した今後の計画

Codex から段階案を提示し、Muse から「基本同意、キーの確認は初期調査と並行、権限点検は認証済み試験の前へ前倒し」と回答を得た。この修正を採用する。日程は約束せず、以下の完了条件を満たして次段階へ進む。これは協議した予定であり、実施済みの作業ではない。

| 段階 | 作業・依存関係 | 完了条件 | 想定担当 |
| --- | --- | --- | --- |
| 1. 導入・配備の事実確認 | 正しい Python import / 配布メタデータ、CLI の固定版、試験 venv の所在、実装ファイルを確認。Builds の最新結果、実際のエラー、配備 SHA、実行イメージの版を照合 | 「ソースあり」「ビルド済み」「配備済み」「実行成功」を分け、各々にファイルパス・SHA・ログ等の根拠がある | Muse: VM と実装。接続可能なホスト: Builds。権限不足時のみ利用者から状態共有 |
| 1 と並行: 認証前提 | bridge の `MUSE_API_KEY` と Code の `META_API_KEY` を区別。Worker 設定と実行コンテナ双方で、値を出さず設定の有無を確認 | 実行環境で必要なキーが利用可能かを確認。未設定・未認証・契約未対応を区別 | 各環境を読める担当。新規キー発行・契約判断は利用者 |
| 2. 試験前の準備 | CLI / SDK / MSP / 依存版と配布物の上流ハッシュを固定。ランチャー自動更新の制御方法を確認。実際の実行ユーザーと隔離ワークスペース、権限プロファイルを決定 | 再ビルドで同じ版を再現でき、SDK API と実装が整合。試験時の書込先とツール権限が明確 | Muse: 固定案と実装点検。実行担当: イメージ確認 |
| 3. 認証済みの最小試験 | 上記完了後、まず回答だけの単発ターン。その後、隔離した領域で小さなファイル編集と意味のある確認を1件行う | `authRequired` ではなく正常終了。回答、差分、確認結果、実行版、終端状態を記録 | 実行コンテナへ接続できる担当。今回は実行しない |
| 4. 運用条件の設計 | 1200 秒設定と Worker / コンテナ / 呼出元の待ち時間を照合。同時実行、キュー、取消、再試行の重複防止、セッション寿命、成果物保存を決める | 遅延・失敗・中断時の状態が説明でき、処理の残留や二重実行を判定できる。再起動後に必要な成果物が残る | Muse: 設計案。Codex: 呼出側との整合確認 |
| 5. 試験導入 | 正常系と認証失敗・タイムアウト・取消等を確認し、限定した利用経路で評価 | 小編集と確認が完了し、差分・エラー種別を追跡できる。戻し方と未対応範囲を記録 | 実装・実行担当。利用範囲の選択は利用者 |

単発同期方式から始める方針で一致した。長時間ジョブ API は実行時間と各経路の上限を測って必要性を判断し、継続セッションは初回成功後に検討する。SDK 自体の機能と、このプロジェクトが実装済みの機能を混同しない。

### 利用者の判断に残す事項

- 認証・契約が不足している場合のサインイン、キー発行、利用プラン。
- 試験用ワークスペースと実行権限。既存の `:unrestricted` という報告を、そのまま確定要件にはしない。
- 実測後の最大実行時間、同時実行数、成果物の保存期間、公開する利用範囲。

「Linux で使えない」という過去の報告は、CLI の起動可否と、認証・契約・SDK の版不整合に分けて調べる。Muse は VM 上で CLI のバージョン表示が動いたと報告しているため、少なくともその記録だけから Linux 全体が非対応とは判断しない。元のエラー表示は未取得で、原因は未特定である。

### 指定された共有ページを踏まえた方針の追加

利用者指定の [Muse の比較回答](https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev/s/5fbe2ba2/4c2dd78a8e71c177) を HTTP 200 で取得し、ページ内の `rawAnswer` から本文を読み取った。主題は `muse serve` と Codex `app-server`、Claude Agent SDK の比較。これを踏まえ、単発実行の成功後に常駐セッション・イベント・承認・取消へ進む案を Muse に提示した。

再協議の結果と移行方針、共通契約、各段階の完了条件は [セッション実行基盤の計画](PLAN.lib.20261110.agent-sessions.md) にまとめる。この計画を、単発試験以降の方針の参照先とする。

Muse は再協議で、単発成功→常駐セッション管理の段階案、既存入口の維持、薄い共通契約、通信切断と取消の分離に同意した。イベント連番と再取得、管理 agent による serve 所有を提案し、計画に反映した。承認の既定動作、コンテナ再作成を跨ぐ保存範囲、保存先、他エンジン対応の優先度は未決として残した。

## 追加の共有ページ: Tailscale WASM による POST

利用者の追加指定により、[wasm-tailscale の説明ページ](https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev/s/5fbe2ba2/7196c30690ddb93f)を HTTP 200 で取得し、`rawAnswer` から回答本文を読んだ。ページ日時は 2026-11-08 21:06:25 UTC、質問は「Tailscale/WASM で POST送信を行うためのクライアント ai-ecoverse/wasm-tailscale について」。記載された技術説明は過去の AI 回答として扱い、独立に一次資料と既存記録を照合した。

- [上流 README](https://github.com/ai-ecoverse/wasm-tailscale/blob/main/README.md) と [型定義](https://github.com/ai-ecoverse/wasm-tailscale/blob/main/package/index.d.ts) を取得。`ipn.fetch` のメソッド・ヘッダー・バイト列本文、応答の `read()` / `cancel()`、ノード状態保存の秘密性を確認した。上流 main の確認は、配備済み版の同一性確認とは区別する。
- このホストの関連リポジトリでは `package.json` / lockfile が `@ai-ecoverse/wasm-tailscale 1.104.1-13` に固定されていることを読んで確認した。
- [既存 SPEC](/root/cloudflare-workers-github-oauth-1/SPEC.cloudflare-workers-github-oauth-1.wasm-muse-bridge.20261108.md)、[成功 REPORT](/root/cloudflare-workers-github-oauth-1/REPORT.cloudflare-workers-github-oauth-1.WASM-BRIDGE-POST.20261108.md)、[配備差分台帳](/root/cloudflare-workers-github-oauth-1/DEPLOYMENT-STATE.md) を確認した。これらの古い「未配備」記述を、現在の配備状態としてそのまま断定しない。
- 2026-11-08 の結果ファイルを直接読んだ。独立した workerd / DO の WASM→Muse POST は HTTP 200・回答マーカー一致。一方、[本体チャット統合結果](/root/cloudflare-workers-github-oauth-1/artifacts/wasm-tailscale-20261108/aichat-live-e2e-result.jsonl) は Job が `done` でも `museTailscale=unavailable` / `exactMarker=false` で、全 Worker bundle の `syscall/js os.Getpid` panic が記録されていた。今回その障害を再現・修正したわけではない。
- 2026-11-09 の台帳には UI と theme の公開記録がある。WASM 全経路・binding・現在の実推論成功をそこから推定しない。現在の配備版・binding と本体統合経路は次段階で確認する。

ページ本文と上記の確認結果を Muse に送り、前回のセッション計画に加える通信経路・認証境界・移行順序を協議した。詳細は [計画の Tailscale WASM 追記](PLAN.lib.20261110.agent-sessions.md#tailscale-wasm-の通信経路を加える方針) にまとめる。今回の作業では新しい tailnet ノード作成、WASM 実 POST 試験、通信経路の設定変更・配備は行っていない。

Muse は Worker / DO を初期候補とし本体統合失敗の特定を優先する案に同意した。ブラウザ直結は当面の対象外とする提案を採用した。結果不明を `delivery_unknown` 等で残すこと、切断と取消を区別することにも一致。Muse の「DO が最適」という評価は現行障害を解消するまで条件付きとし、明示再送にはサーバー側の重複抑止も必要と補足した。将来の Code 制御 API の受信制約や認証済み操作の成立は、今回確認できていない。

## 追加の共有ページ: Muse CLI オプション

利用者指定の[CLI オプション表](https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev/s/5fbe2ba2/e25d9f3922797465)を HTTP 200 で取得し、`rawAnswer` の本文を読んだ。ページ日時は 2026-11-09 21:43:45 UTC。CLI 1.4.13〜1.4.14 の説明とされる過去の Muse 回答であり、現在の CLI / SDK の契約としてそのまま採用しない。

このホストでの独立確認:

- 公式 [Configuration](https://dev.meta.ai/docs/muse-code/configuration) と [Permissions](https://dev.meta.ai/docs/muse-code/permissions) を取得した。TUI / exec のフラグ集合、ログ保持と再開の関係、承認と OS サンドボックスの区別を確認。モデルの利用可否、対象実機での隔離成立、全 CLI フラグの受理までは確認していない。
- 公式文書は、新規セッションの permission profile の既定と approval mode を別に説明している。ページの「on-request が既定」を、実機で Ask me プロファイルが適用済みという意味には解釈しない。
- Linux では動作する bubblewrap helper が必要との公式説明を確認した。CLI の起動、モデル認証、シェル隔離の成立は別々に点検する。
- [PyPI 1.4.14 メタデータ](https://pypi.org/pypi/muse-code-sdk/1.4.14/json)から wheel をメモリへ取得し、公開メタデータの SHA-256 と一致することを確認して `muse_code/facade/client.py` を読んだ。インストールや import 実行はしていない。
- 同ファイルの `MuseClientSpawnOptions` は `args` / `cwd` / `env` 等を持ち、`spawn` はオプション型を受け取る。`StartSessionOptions` は `approval_mode`、`provider_id`、`model_id`、workspace、`permission_profile` と `require_permission_profile` を持つ。CLI のオプション表を SDK の同名引数表とはしない。
- `require_permission_profile=True` は指定 profile の適用を session 状態または読戻しで確認し、不一致・未証明なら `PermissionProfileNotApplied` を返す実装だった。設定値を渡すだけで十分とせず、この確認を試験前の候補にする。対象 agent が現在それを使っているかは、このホストから確認できていない。

ページ本文とこれまでの計画を Muse へ送り、固定版のヘルプ・実効設定・無人運用・ログ保持を計画にどう加えるか協議した。詳細は [CLI 設定の適用方針](PLAN.lib.20261110.agent-sessions.md#cli-オプションと-sdk-設定の適用方針) に記載する。

### Muse の固定版ヘルプ確認と合意

Muse は `/home/hatch/.local/bin/muse-bin-1.4.14-R7309.1` の `--help`、`exec --help`、`serve --help`、`schema --help` を直接確認し、更新ランチャーは使っていないと回答した。以下は **Muse による help の確認報告** であり、このホストから実行した結果や設定適用試験ではない。

| 項目 | 固定版 help についての報告 | 計画への扱い |
| --- | --- | --- |
| `serve` | `--model`、`--preset`、`--provider`、`--contributor-mode`、`--no-session-log`、`-c`、sandbox 関連を掲示 | TUI / exec の全引数を流用しない |
| `serve` の承認・effort | `--approval-mode`、`--disable-approval`、`--yolo`、`--permission-profile`、`--reasoning-effort` は掲示されていない | 掲示がないことと、全設定経路が存在しないことを同義にしない。SDK / 設定経路を別確認 |
| ネットワーク値 | 全体 help は `restricted` / `enabled` / `proxy-only`。`exec` / `serve` help は列挙を省略 | 公式現行文書の `unrestricted` 表記との差を残し、対象版で受理・適用されるか確認してから指定 |
| provider | 全体 / `serve` は `echo` / `meta` / `local`、`exec` は `echo` / `meta` | ページの例を共通 enum としない。利用可能性は別確認 |
| permission profile | 全体 / `exec` に `--permission-profile`、`serve` には掲示なし | SDK の session 選択と host 引数を混同しない |
| exec 固有項目 | `--json`、`--prompt-file`、`--session-id`、`--max-model-steps`、`--disable-request-user-input` を確認 | SDK に同名の制御があるとは推定しない |
| 終了コード・既定値・隔離 | ページの終了コード一覧、profile 既定、bubblewrap の成立は help だけでは確認できない | 実行結果と公式文書を別々の根拠として扱う |

Muse は固定版 CLI / SDK 対応表の作成、実効設定の記録、隔離不成立時に自動で権限を緩めないこと、SDK 単発を主経路とすること、継続利用で `--no-session-log` を安易に既定にしないことに同意した。承認待ち・質問待ちを表現し、フラグだけで無人化できたとは判断しない点も一致した。

今回 Muse はこのホストの `/root/lib/PLAN...` を読めず、現行 agent の再点検も未確認と回答した。以前確認した Muse VM 側 `/home/hatch/workspace/kernel/muse-code-test/container-agent.py` の導入報告とは区別し、今回の help 調査だけで実装差分が確定したとはしない。SDK 1.4.14 の型に関する根拠は、このホストで読んだ配布物によるもの。

## 専用 Worker の作成依頼

利用者の「Muse Code SDK と Tailscale/WASM からの POST 送信を使って専用 Worker を作ってと依頼して」という追加指示により、Muse へ実装依頼を送信した。これまでの調査・協議のみという制限をこの新規作業には適用せず、適用される既存のビルド条件等は維持するよう伝えた。

依頼した構成は、専用 Worker / DO → Tailscale WASM の実 POST → 認証された受信 API → Muse Code Python SDK / `muse serve` → 隔離 workspace。既存の `muse-code-test` の実ファイルを確認して活用し、既存サービスと重複・混同しないことを指定。単なる bridge 応答を SDK 実行成功として扱わず、認証済み単発と小編集・確認を最初の到達点にした。

秘密値を記録しないこと、権限を自動で緩めないこと、WASM を native relay で代用しないこと、結果不明時に自動再送しないことを含む協議済み要件を添えた。作成したパス・Worker 名・差分・検証結果・未確認範囲を返すよう依頼した。送信時点では実装の完了・配備成功を確認していない。

### フレームワークは案のみの追加依頼

利用者から「フレームワークもあったほうがいいならまずは案だけ聞いといて」と追加指示があった。専用 Worker の作成依頼は維持し、フレームワークの必要性、素の Worker / DO との比較、候補と採用条件、Python 受信側の変更要否を Muse に質問した。フレームワークの導入・依存追加・移行はこの追加依頼では行わず、提案に留めるよう明示した。

### 現稼働 Worker からの移植という位置づけ

続いて利用者から「現に動いてる Worker からの移植という位置づけ」と指定された。Muse へ同じ作業の優先する指示として追記し、移植元の現稼働版を特定して根拠を残すこと、ソース・binding・設定名・Job / 認証 / エラー処理の対応表を作ること、Muse Code SDK の追加点を移植部分と分けることを伝えた。未配備のローカル変更を現稼働機能と混同せず、既存本番を変更・停止しない方針。移植元を特定できない場合は不足情報を報告し、新規設計で代用しないよう依頼した。フレームワークは引き続き案のみ。

さらに利用者は「今あるものの代替となり得るシンクライアント的な位置づけ」と指定した。Muse へ、Worker は必要最小限の UI / API 受付・認証・WASM POST・Job / イベントと結果の受け渡しに絞り、SDK / serve / workspace の実行は受信側に置く方向を伝えた。代替対象の操作と未対応範囲を対応表で明確にし、既存アプリ全体の再実装を前提にせず、既存本番の切替は行わないよう依頼した。

WASM が関わるため構想段階からの協議提案も求めるという追加指示を、上記要件とまとめて Muse に送った。Worker / DO 内 WASM と他の通信実行場所の比較、現稼働版と移植対象の特定、最小 PoC の成功条件、薄い構成と実行側の責務分担を提案するよう依頼した。WASM を使わない案を、要件を満たす実装として黙って代用しないことも明示した。

最初の作成依頼は送信後 360 秒で応答待ちがタイムアウトした。受領・実作業の実施・完了のいずれもこの通信結果だけでは確認できず、送信結果不明として扱う。追加の方針連絡は別途送信済みだが、最初の作成依頼そのものは重複実行を避け再送していない。

### 最新の範囲: 段取りの協議に絞る

利用者の「まずはどういう段取りで進めるかだけ協議して」に従い、こちらの実装作業を停止。Muse にも作成・設定変更を進めず、移植範囲→対応関係→最小 PoC の順序だけを協議する追加連絡を送った。直近の計画は [NEXT-STEPS](projects/muse-code-thin-client/NEXT-STEPS.md)、現状は [STATUS](projects/muse-code-thin-client/STATUS.md)、依頼本文と応答状態は同プロジェクトの `coordination/` に保存する。

## この作業の変更範囲

このホストでは調査結果を文書に追記する。SDK のインストール、認証情報変更、サービス再起動、Cloudflare デプロイは実施していない。Muse 側にも調査・協議のみを依頼している。
