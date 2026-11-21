# NOTICE: monitor の SDK 系 section のエラー2件と対処結果

日付: 2026-11-21
対象: `muse/sdk-health.sh` / `muse/sdk-profiles.sh` / `muse/sdk-sessions.sh` / `muse/sdk-ts-health.sh`（receiver の monitor section sdkhealth / sdkprofiles / sdksessions / sdkts）
発生場所: muse-vm の `~/lib`（配置済みスナップショット）

2026-11-21 夜、muse-monitor の表示が復旧した直後に、SDK 系の section が軒並みエラーになっているのが見つかった。実測した内容と対処結果を記録する。

## 1. sdkprofiles / sdksessions: 本体と SDK のバージョン不一致

- 症状: 両 section とも rc 1 で Python の traceback を表示する。末尾は `MuseHostMismatchError: the muse host (host version 1.4.20) serves schema fingerprint sha256:283b1b12… but this muse-code-sdk requires sha256:ef311d2d…; install host version 1.4.15`。
- 原因: 本体の muse CLI が自動更新で 1.4.20 に上がっていた一方、venv（`~/.local/share/muse-sdk-venv`）の muse-code-sdk は 1.4.15 のままだった。この SDK は本体と同版でないと handshake を拒否する。sdkhealth の表示にも両バージョンが併記されており、ここからも読み取れた。
- 対処: 利用者の指示で SDK 側を上げた。venv に `pip install muse-code-sdk==1.4.20`。
- 結果: sdkhealth / sdkprofiles / sdksessions の3つとも rc 0 を receiver 経由で確認した（2026-11-21 20:24 JST）。

## 2. sdkts: `@muse-code/sdk` が入っていない

- 症状: rc 1 で `Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@muse-code/sdk' imported from …/lib/muse/ts/dist/common.js`。
- 原因: `muse/ts/dist` はあるが node_modules が配置されておらず、依存が入っていなかった。加えて `muse/ts/package.json` のピンも 1.4.15 で、入れたとしても本体 1.4.20 と版が合わなかった。
- 対処: `~/lib/muse/ts` で `npm install @muse-code/sdk@1.4.20`。配置側の package.json と package-lock.json のピンも 1.4.20 に上がった。
- 結果: `sdk-ts-health.sh` の直接実行で正常（`@muse-code/sdk: 1.4.20`）を確認し、receiver 経由の sdkts も rc 0 を確認した（2026-11-21 20:26 JST）。

## 3. 残件と注意

- リポジトリ側の `muse/ts/package.json` のピンは 1.4.15 のままである。今回の対処は配置側（`~/lib`）だけなので、lib を再配置すると sdkts は再び 1.4.15 になる。リポジトリ側のピン更新が別途必要。
- 本体の muse が自動更新されるたびに、Python / TypeScript 両 SDK の追随が必要になる構造は変わっていない。版がずれている間、SDK 系 section は上記の形で落ちる。
- 確認時の注意: receiver には section 結果のキャッシュがあり（古い結果を返しながら裏で取り直す。stale の上限は既定300秒）、対処直後は古い応答が返ることがある。応答の `ts` が対処時刻より後であることを見てから判定すること。
