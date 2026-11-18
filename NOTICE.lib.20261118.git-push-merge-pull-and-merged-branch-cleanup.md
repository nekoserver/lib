# NOTICE: push → PR → マージ → mainのpull と、mainに取り込み済みのブランチの検出・削除（2026-11-18）

日付: 2026-11-18（UTC）
作成: opus-5.5（Claude Opus 5.5、Claude Code）
対象: `nekoserver/lib`（`/root/lib`。`/var/www/html/lib`はこのチェックアウトのbind mount）
根拠: 2026-11-18に実際に行った作業（PR #157・#158・#159、リモートブランチ112本の削除）。下のコマンドはすべてこの日に実行して動いたもの。

---

## 1. 流れ

**対象**: 1つの変更を`main`に入れて、ローカルを`main`に戻すまで。

| 順 | すること | 誰が |
|---|---|---|
| 1 | `origin/main`から作業ブランチを切る | エージェント |
| 2 | コミットして、ブランチをpushする | エージェント |
| 3 | GitHub Web API（curl）でPRを作る | エージェント |
| 4 | PRを確かめてマージする | **利用者**（エージェントはマージしない。6章の3） |
| 5 | ローカルを`main`に戻してpullする | エージェント（利用者の指示で） |
| 6 | マージ済みのブランチを消す（ローカル・リモート） | エージェント（利用者の指示で。3・4章） |

---

## 2. push・PR・pull

**対象**: 1章の1〜3と5のコマンド。

```sh
cd /root/lib
git fetch -q origin
git switch -c <種類>/<内容>-<YYYYMMDD> origin/main   # 例: fix/muse-exec-bits-20261118
# … 変更 …
git add <ファイル>
git commit                                          # 末尾に Co-Authored-By の行
git push -u origin <ブランチ>
```

PRは`CLAUDE.md`の手順どおりGitHub Web API（curl）で作る。`gh`コマンドは使わない。

- トークン: `CLAUDE.md`は`.github_token`から読むと書いているが、2026-11-18のこのチェックアウトには`.github_token`が無かった。環境変数`GH_TOKEN`（`nekoserver`のアカウント）で同じAPIを呼んだ。
- 本文は改行や記号を含むので、ファイルに書いてから`python3 -c 'json.dumps(...)'`でJSONにし、`--data-binary @ファイル`で送る（シェルの引用符で壊さない）。
- PRの本文の更新は`PATCH /repos/nekoserver/lib/pulls/<番号>`に`{"body": …}`。

マージの後（利用者がマージしたと言ったら）:

```sh
git switch main
git pull --ff-only origin main      # 早送りできないときは止まる（勝手にマージコミットを作らない）
git status -sb                      # "## main...origin/main" だけなら一致
```

**bind mountに注意**: `/var/www/html/lib`は`/root/lib`のbind mountなので、ローカルで切り替えたブランチの内容が、そのまま8445（管理者の入口）で配信される。作業が終わったら`main`に戻す。

---

## 3. mainに取り込み済みのブランチの検出

**対象**: 消してよいブランチの判定 — 祖先関係だけでは足りない。

| 判定 | コマンド | 何が分かるか |
|---|---|---|
| A. 祖先 | `git merge-base --is-ancestor <sha> origin/main` | ブランチの先頭が`main`の祖先なら、全コミットが`main`にある（マージコミットの方式で入った場合） |
| B. パッチが同じ | `git cherry origin/main <ブランチ>` | 行頭`-`は同じ変更が`main`にある、`+`は無い。cherry-pickやrebaseで別のコミットとして入った場合を拾う |
| C. PRがマージ済みで、先頭が同じ | `GET /repos/nekoserver/lib/pulls?state=all`の`merged_at`と`head.sha` | PRのマージの後にpushされたコミットが無いこと |
| D. 開いたPRが無い | 同上の`state == "open"` | 作業中のブランチを消さない |

消してよいのは「(A または C) かつ D」。Cで`head.sha`が違うブランチは、マージの後にコミットが足されているので、Bで中身を確かめる。

2026-11-18の実例:

| ブランチ | 判定 | 結果 |
|---|---|---|
| 110本 | A（すべて祖先） | 削除 |
| `codex/llm-chat-react-page`（PR #50） | Aでない、Cで先頭が違う。Bではすべて`-`（同じパッチが #51 で`main`に入っていた。`git patch-id --stable`でも一致） | 削除 |
| `feat/tailnet-health-xfu-20261118`（PR #153） | Cで先頭が違う。Bで`+`が1つ（#153のマージの後にpushされたNOTICE） | NOTICEを #159 で`main`に入れてから削除 |
| 開いたPRのある8本、PRも無く`main`にも無い3本 | D、またはA・B・Cのどれでもない | 残した |

---

## 4. 削除

**対象**: 3章で消してよいと判定したブランチを消す手順。

### 4.1 先に記録する

消す前に、名前・先頭のコミット・理由を残す。2026-11-18の分は`/root/.cache/lib-deleted-branches-20261118.tsv`（112行、タブ区切り）。どのコミットも`main`に含まれる（または同じパッチがある）ので、1本戻すときは:

```sh
git push origin <sha>:refs/heads/<ブランチ>
```

### 4.2 リモート

```sh
git push origin \
  --force-with-lease=refs/heads/<ブランチ>:<記録したsha> \
  :refs/heads/<ブランチ>
git fetch -q --prune origin          # ローカルの追跡ブランチ（remotes/origin/...）も消す
git ls-remote --heads origin         # 消えたことを確かめる
```

- `--force-with-lease=<ref>:<sha>`: 判定した後に誰かがpushしていたら、消さずに拒否される。
- 多いときは30本ずつに分けて1回のpushにまとめる（2026-11-18は110本を4回）。

### 4.3 ローカル

```sh
git branch -d <ブランチ>    # mainにマージ済み（祖先）なら消える
git cherry main <ブランチ>  # -d が拒否したら、全行が "-" であることを確かめてから
git branch -D <ブランチ>
```

---

## 5. 2026-11-18に起きたこと

**対象**: この手順を書くきっかけになった事例。

| 事例 | 何が起きたか | 教訓 |
|---|---|---|
| PR #157 | 訂正のコミット（`bbfad2b`）をpushする前に、利用者が初版のままマージしていた。訂正はブランチにだけ残った | **追加でpushする前に、PRがまだ開いているかを確かめる**（`GET /pulls/<番号>`の`state`・`merged`）。マージ済みなら、`origin/main`から新しいブランチを切り、`git cherry-pick`で移す（#158で行った） |
| PR #153 | マージの後にNOTICE（`3724117`）がpushされ、`main`に入らないままだった | 同上。3章のCで`head.sha`が違うブランチとして見つかった |
| PR #159 | エージェントがPRを作った6秒後にAPIでマージした。トークンが`nekoserver`のものなので、GitHubには利用者がマージしたと記録された | 6章の3 |
| 保存スクリプトの失敗 | 一括削除の前の記録処理（`python3 -c`の中の引用符）が構文エラーになり、記録が空のまま削除の処理に進んだ。対象が空だったため何も消えなかった | 記録はスクリプトのファイルに書く。**記録の件数が対象の件数と一致することを確かめてから消す** |

---

## 6. 守ること

1. 作業ブランチは必ず`origin/main`から切る。`main`に直接コミット・pushしない。
2. 追加のpushの前に、PRがまだ開いているかを確かめる。
3. **PRのマージは利用者が行う。** エージェントはPRを作ったらリンクを渡して止まる。「mainに入れて」と言われても、マージまで行うかを確かめる。`GH_TOKEN`は利用者のアカウントなので、エージェントのマージも利用者の操作として記録される。
4. マージの後は`git pull --ff-only`。早送りできなければ止まって報告する。
5. ブランチを消すのは、3章の判定を満たし、4.1の記録を残してから。リモートは`--force-with-lease`で消す。
6. 作業が終わったらローカルを`main`に戻す（bind mountで配信に出るため）。
