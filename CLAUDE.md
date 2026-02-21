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
