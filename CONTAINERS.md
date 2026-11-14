# コンテナの一覧(特殊な仕組み・根拠・設定状況・共通項目)

各リポジトリの Cloudflare Containers を1か所で見比べるための表。値は各リポジトリの main(2026-11-11 時点。本体は 2026-11-14 時点)から集めた。

| リポジトリ | main |
|---|---|
| nekoserver/cloudflare-workers-github-oauth-1(本体) | `13e7fe4` |
| nekoserver/dynamicneko | `83ef48b` |
| nekoserver/redmine | `ec16806` |
| nekoserver/musevm | `b624768` |
| nekoserver/musevm-kernel | `dd35fe6` |

コンテナを変えたら、同じ作業の中でこの表も直す。

## 1. 設定状況

| コンテナ | リポジトリ | Dockerfile | ベース | instance_type | イメージの扱い | 固定のずれの検査 | 作り直しのしかた |
|---|---|---|---|---|---|---|---|
| demo(DemoContainer) | 本体 | `containers/demo/Dockerfile` | ubuntu:26.04 | standard-1 | 本番のデプロイ(Workers Builds の `npx wrangler deploy`)で Dockerfile から作る(2026-11-13 に digest の固定から戻した) | `src/cf-containers-image-lock.test.ts`(`wrangler.toml` の Dockerfile のパスとビルド引数、戻す先の digest の書式) | 本番のデプロイのたびに作る。GitHub Actions は使わない(2026-11-13、本体 `CLAUDE.md` ルール39)。git・Apache のパッケージは別の環境で作ってリポジトリに置く |
| sandbox-terminal(SandboxTerminal) | dynamicneko | `containers/sandbox-terminal/Dockerfile` | node:24-trixie-slim | 既定(未指定) | ビルド済みを digest で固定 | `containers/sandbox-terminal/image.lock.json` と `test/terminal-image-lock.test.ts` | 導入中: GitHub Actions `container-image` が作り直して PR を出す(dynamicneko#449)。それまでは Docker のある環境で手作業 |
| RedmineContainer | redmine | `Dockerfile` | ubuntu:26.04(多段) | standard-1 | ビルド済みを digest で固定(本番・プレビュー) | `image.lock.json` と `test/image_lock_test.py` | GitHub Actions `container-image` が作り直して PR を出す(シークレットの設定待ち) |
| musevm | musevm | `Dockerfile` | debian:trixie-slim | basic | デプロイのたびに Dockerfile からビルド | なし(毎回ビルドするので不要) | デプロイ(`wrangler deploy`)で自動 |
| musevm-kernel | musevm-kernel | `Dockerfile` | debian:trixie-slim(多段) | basic | デプロイのたびに Dockerfile からビルド | なし | デプロイで自動(カーネルは Base64 の分割から組み直す) |

## 2. 特殊な仕組みと、それが必要になった根拠

| 仕組み | 対象 | 根拠(何が起きたか) | 記録 |
|---|---|---|---|
| イメージを digest で固定し、デプロイのたびにビルドしない | 本体・dynamicneko・redmine | 本体: Workers Builds の Docker ビルドが `runc ... mounting "proc" ... operation not permitted` で落ち続けた(2026-11-11)。dynamicneko: 毎回のビルドで準備が15分を超えて失敗した(PR #415〜#422)。redmine: 本番のイメージをそのまま固定した(#22、2026-10-28) | 本体 `NOTICE.cloudflare-workers-github-oauth-1.20261111.md`、dynamicneko `CLAUDE.md`、redmine `BUILD.status.md` |
| 固定のずれの検査(`image.lock.json` の入力ハッシュ) | 本体・dynamicneko・redmine | 固定していると、Dockerfile を変えてもイメージを作り直すまで本番に入らない。検査が無い redmine では、Apache 2.4.71(#25)と Node 26.13.1(#26)がマージされても本番に入らなかった | redmine `SPEC.redmine.20261111.image-lock.md` |
| イメージの作り直しを GitHub Actions で自動にする | redmine・本体(導入中)・dynamicneko(導入中) | Docker のある環境が手元に無く、手作業では更新が止まる。本体の T3 0.1.9・Node.js 26.13.1(#2566)もマージ後に本番へ入らなかった | redmine `SPEC.redmine.20261111.image-lock.md`、本体 `SPEC.cloudflare-workers-github-oauth-1.20261111.container-auto-build.md`、dynamicneko `SPEC.dynamicneko.20261111.terminal-image-auto-build.md` |
| ソースから作る物は別の環境でビルドしてリポジトリに置き、Dockerfile では COPY と sha256 の照合だけ | 本体(git・OpenSSH・Apache) | cf-container(standard-1)は CPU が足りず、コンパイルで時間切れになる(ユーザー指定 2026-11-07) | 本体 `CLAUDE.md` コンテナビルドのルール8、`containers/demo/packages/README.md` |
| ソースビルドは許可の表にあるものだけ | 本体 | gh・jj を毎回ソースから作り、本番ビルドで約19分使っていた(2026-10-31) | 本体 `CLAUDE.md` ルール44、`src/cf-containers-source-build-allowlist.test.ts` |
| ビルド成果物を GitHub Releases に保存して使い回す(`REQUIRE_BUILD_ARTIFACTS=1`) | redmine | 同じソースを毎回コンパイルし直していた(2026-10-27) | redmine `BUILD.artifacts.md`、`POLICY.build-artifacts.md`、`AGENTS.md` |
| ソースをリポジトリに同梱(`vendor/sources`) | redmine | 最新版しか置かない配布元(downloads.apache.org)から固定した版が消える | redmine `sources.lock.json`、`AGENTS.md` コンテナビルドのルール1 |
| npm の全体設定で、Claude CLI のインストール後の処理(`node install.cjs`)だけを許す(`allow-scripts=@anthropic-ai/claude-code`) | 本体 | 起動後の Claude Code の自動更新(2.1.323→2.1.325)が `--allow-scripts` 無しで `npm install -g` を実行し、npm 12 が処理を止めたため、`claude` の入口が仮のファイルのまま残って動かなくなった(2026-11-14) | 本体 `src/cf-containers-claude-cli.test.ts`、lib `SETTINGS.claude-host.20261102.md` |
| 外部ツールの挙動を契約テストに書き、版を上げる前にテストを直す | 本体(T3・Codex・Tailscale) | T3 の挙動を推測で直しては外すことを繰り返した(2026-10-28〜31) | 本体 `CLAUDE.md` ルール43、`src/cf-containers-t3-contract.test.ts` |
| Tailscale を Go のソースからビルド | dynamicneko(本体は公式のビルド済みへ戻した) | エージェントのサンドボックスから配布元に届かなかった(本番には関係ない理由)。次の作り直しで公式のビルド済みへ替える予定 | dynamicneko `CLAUDE.md` コンテナイメージの項3 |

## 3. 主な版(main 時点)

| パッケージ | 本体 demo | dynamicneko | redmine | musevm | musevm-kernel |
|---|---|---|---|---|---|
| Node.js | 26.13.1 | node:24(ベースイメージのタグ) | 26.12.1(26.13.1 は #26) | 26.13.1 | — |
| Apache httpd | 2.4.71(別環境でビルドしたパッケージ) | apt の apache2 | 2.4.71(同梱ソース) | 2.4.71(ソースから) | — |
| Tailscale | 1.104.7 | 1.104.4(Go のソースから) | 1.104.1 | 1.104.5 | 1.104.5 |
| cloudflared | 2026.11.0 | 2026.10.6 | 2026.10.1 | 2026.10.7 | — |
| gh | 2.104.0 | — | 2.103.0 | 2.103.3 | — |
| Codex CLI | 0.169.0 | — | 0.164.0 | 0.166.0 | — |
| その他 | git 2.56.1、OpenSSH 10.6p2、Ruby 4.0.9、jj 0.47.1、Claude CLI 2.1.323、T3 0.1.9 | — | Ruby 4.0.9、Passenger 6.2.1、Redmine 7.0.2、OpenSSL 3.5.9 | Wrangler 4.156.2 | カーネル 7.3.4 |

固定しているコンテナ(dynamicneko・redmine)は、Dockerfile の版と本番のイメージの中身が一致するとは限らない。本体は 2026-11-13 から本番のデプロイで Dockerfile から作るため、デプロイの後は Dockerfile の版になる。ただし起動後の自動更新(Claude CLI など)で版が進むことがある。本番の中身は、固定したイメージを作ったときの版である。本体は D1 の `cf_container_snapshots` に実際の版が記録される。

## 4. 共通項目(すべてのコンテナに適用)

| 項目 | 内容 | 根拠 |
|---|---|---|
| 版とハッシュで固定 | 外部から取る物は版とハッシュで固定し、ハッシュは上流が公開する値と照合する。`curl \| tar` のように検証なしで展開しない | 各リポジトリの `CLAUDE.md`/`AGENTS.md` コンテナビルドのルール2(2026-11-06) |
| 消える取得元に頼らない | 最新版しか置かない配布先には、恒久的なアーカイブへのフォールバックか、リポジトリに保管した成果物を使う | 同ルール1 |
| 取得できることを先に確かめる | 版や URL を変えたら、ビルドの前に `curl -fsSIL` で確かめる | 同ルール3 |
| 失敗を隠さない | `a && b \|\| c` を使わず、`set -eu` と `if` で分ける | 同ルール4 |
| 設定の書き換えは結果を検査 | `sed` の直後に `grep -q` で確かめる | 同ルール5 |
| 実行ユーザーで動くことを確かめる | 非 root のサービスは書き込み先の所有権を設定し、ビルド中に起動して確かめる | 同ルール6 |
| 未実施のビルドを成功と報告しない | 実行できないときは、確かめた範囲と未確認を分けて書く | 同ルール7 |
| Docker ビルドの実行条件 | エージェントのコンテナでは Docker ビルドをしない(Docker デーモンが無い・条件付き) | 本体 `AGENTS.md`、redmine `AGENTS.md`、dynamicneko `CLAUDE.md` |
| 公式のビルド済みを優先 | 配布元のリリース・公式パッケージ・apt・公式イメージを先に探す。ソースビルドは理由を書いて許可を得たものだけ | 本体ルール44、dynamicneko コンテナイメージの項3、redmine `POLICY.build-artifacts.md` |
| PR にコンテナの再ビルド・再起動の要否を書く | `## コンテナ` の節に「再ビルド: 必要/不要」「再起動: 必要/不要」と根拠 | 本体 `CLAUDE.md` ルール47 |
