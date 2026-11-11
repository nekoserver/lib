# プロジェクト指示

## PR作成手順

作業完了後のプルリクエストは、GitHub Web API (curl) で作成すること。
`gh` コマンドは使用不可。

### 手順

1. トークンを `.github_token` ファイルから読み取る
2. GitHub API (`https://api.github.com/repos/nekoserver/lib/pulls`) に POST する
3. ベースブランチは `main`

### コマンド例

```bash
TOKEN=$(cat .github_token)
curl -s -X POST "https://api.github.com/repos/nekoserver/lib/pulls" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "PRタイトル",
    "head": "ブランチ名",
    "base": "main",
    "body": "PR本文"
  }'
```

### 注意

- トークンファイル (`.github_token`) は `.gitignore` に登録済み。絶対にコミットしないこと。

## 変数・シークレット・設定スイッチを増やさない(ユーザー指定、2026-11-11)

無意味な変数の濫発で、利用者が「どの鍵をどこに入れればよいか」分からなくなり、意味の無いエラーで時間を失った(muse-monitorで、同じTailscaleの鍵を `TS_AUTHKEY` と `TS_API_KEY` の2つに分け、片方だけ設定されて「ログインの承認待ち」になった。鍵を誰も把握しておらず、状態を確かめることもできなかった)。

- **ユーザーの承認なしに、新しい環境変数・シークレット・設定スイッチを足さない。** 「将来使うかもしれない」「汎用にしておく」は理由にならない。
- **同じ値を、別名の変数に分けない。** 1つの用途に1つの名前。
- 足す必要があると判断したら、先にユーザーに「何のために、どの名前で、どこに設定するか」を伝え、承認を得る。足したら、READMEの鍵の表・`wrangler.toml` のコメント・テストを同時に直す。
- 既存の変数で足りないかを、先に確かめる。使われていない変数は足さない・残さない。
- 未設定のときに黙って別の値や経路に切り替えない。どの鍵を使ったか(名前だけ、値は出さない)を状態に出す。
