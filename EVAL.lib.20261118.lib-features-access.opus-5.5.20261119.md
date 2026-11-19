# 評価: libの機能と入口ごとの制限（2026-11-19、opus-5.5）

評価日: 2026-11-19（UTC）
評価: opus-5.5（Claude Opus 5.5、Claude Code）
評価の基準: [`SPEC.lib.20261118.lib-features-access.md`](SPEC.lib.20261118.lib-features-access.md)（2026-11-19の改訂版、SHA256 `1266920912ad448460cc3aec57a05f9bfb076fb988053060e7c454d61b84f2c7`）
評価対象: 本体のdemoコンテナ（2026-11-18 22:10起動）のApache（8443・8445）と、libの`main`（`592f438`）
区分: [`SPEC.lib.20261119.spec-eval-refresh.md`](SPEC.lib.20261119.spec-eval-refresh.md)の手順2（EVALが無かった。[`EVAL.lib.20261118.opus-5.5.md`](EVAL.lib.20261118.opus-5.5.md)はこのSPECを参照しているが、評価の基準は`SPEC.lib.20261118.opus-5.5.md`）

---

## 総合

公開側（8443）の制限はSPECどおり。11-18の版の7章（bind mountなし、8445に中継なし）と2章の8445の列は古くなっていたので、改訂で測り直した。bind mountの結果、管理者の入口（8445）からコマンドを実行するSSIや`.git/config`が開ける。管理者だけの入口なので公開ではないが、目標の状態（REQ-LA-6）とは食い違う。

| 要件 | 判定 |
|---|---|
| REQ-LA-1〜4 | 充足 |
| REQ-LA-5 | 充足（tunnels API・ストリームは実物、ほかはSPECの3章のコードの記述による） |
| REQ-LA-6（目標） | 未充足（SPECどおり未実現） |

---

## 要件ごとの評価

| 要件 | 判定 | 根拠（2026-11-19、コンテナの中から） |
|---|---|---|
| REQ-LA-1 | 充足 | 8443で、2章の表のすべてのパス（tunnels API・チャット・SSI・CGI・Muse・`keys`・`ops`・文書・`.git`）と`/debug`・`/admin`が403 |
| REQ-LA-2 | 充足 | 署名なし403、不正な署名401、署名付き200。`/lib/api/tunnels/extra`は署名ヘッダー付きでも403 |
| REQ-LA-3 | 充足 | 起動オプションon（`lib-chat-route-access.conf`あり）。`?via=aichat-panel`の埋め込みページは401（アプリへ届く）、`?via=bogus`・経路IDなしは403、Cookie付きの`/lib/api/chat/session`は401 |
| REQ-LA-4 | 充足 | `ss -ltn`で8445は`127.0.0.1`だけ。8091・8092も`127.0.0.1` |
| REQ-LA-5 | 充足 | tunnels APIの署名の照合（401）、ストリームのOriginの照合（8445の`session`が403 `origin_rejected`）、埋め込みページのログイン（401）を実物で確かめた |
| REQ-LA-6 | 未充足 | 8445で`/lib/date.shtml`・`/lib/printenv.shtml`（コマンドを実行）、`/lib/ops/llm_worker.py`、`/lib/CLAUDE.md`、`/lib/.git/config`、`/lib/keys/`が200 |

---

## 提案（未実施）

1. 本体SPEC 2026-11-13の拒否の表（`.git`・`ops`・`test`・`keys`、`.py`・`.md`、コマンドを実行するSSI）を、本体のイメージの`apache-lib.conf`に入れる。入るまでの間、libの`restore-claude-host.sh`で入れるかを決める（lib側で足すと、イメージとの二重管理になる）。
2. `/lib/api/tunnels`が8445でソースを文字のまま返す件（`api/tunnels`が`tunnels.rb`へのsymlink）を、8445でもCGIにするか拒否する。
3. `muse/dashboard/ask.cgi`が8445の`GET`で500になる（[`muse/EVAL.opus-5.5.20261119.md`](muse/EVAL.opus-5.5.20261119.md)）。

---

## 確かめていないこと

- 入口B（本体ワーカー → `server.js` → 8445）と入口C（dynamicneko）を実際に通した結果。
- 2026-11-13・14のイメージの例外が、どこから入っていたか（11-18から変わらず）。
