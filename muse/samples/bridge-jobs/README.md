# bridge-jobs のキューの見本

`bridge-jobs.sh` と `recent-jobs.sh` を手元で試すための見本。実際のキュー(`~/workspace/bridge-jobs`)と同じ形。

```bash
sh ../../bridge-jobs.sh .
```

```bash
sh ../../recent-jobs.sh .
```

| ファイル | 内容 |
|---|---|
| `queue/*.json` | 未処理のジョブ。`status` が `queued` のものだけが一覧に出る(優先度の降順、同点は `created` の昇順) |
| `done/*.json` | 済んだジョブ。`bridge-jobs.sh` は件数だけを出す |
| `done/*.md` | 結果の報告。`recent-jobs.sh` は新しい順に見出しを出す |
