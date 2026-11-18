利用者から追加依頼：「preprintを使って何かできないかをMuseと協議して」。今回は提案・協議のみ。コード作成、インストール、ブラウザ操作、サインイン、設定変更はしない。
このホストでpreprint --version=0.1.2と--helpを確認。@supermemory/preprint（supermemoryai/preprint）の公式READMEを取得し、実Chromiumのタブをmarkdownへ投影、1行のaction追記で操作、再読込して最新refを使う、console/画像等を記録という機能を確認した。ただし今回ブラウザ操作は試していない。
現在の課題は、現Workerからの薄い専用クライアントへの移植計画、Tailscale WASM→HTTP POST→Muse Code SDK、認証状態・Jobと実回答の区別、未解決事項の整理、PRへの検証根拠保存です。
候補案：公開画面の表示/接続状態の確認、移植前後UIの差分・console採取、同一Jobの再訪と結果表示の確認、仕様書・共有ページを読む補助。preprint自体をHTTP API/SDK結果検証やWASM起動の代用にしない。利用者の既存ログインprofileを勝手に使わず、初回はno-profileか独立sessionで状態変更しない画面から始める案です。
これに対して有用な用途3件、推奨する最初の小実験1件（対象/段取り/完了条件/取得成果物）、Playwright等の既存手段との使い分けと制約、追加の有望案を日本語400〜700字で回答して。使っていない機能を実測済みとしない。
