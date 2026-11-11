#!/usr/bin/env python3
"""sdk-profiles.sh の実体。ホストの権限プロファイル一覧とモデル一覧を出す。

読み取り専用: セッションは作らず、permissionProfile/list と
list_models だけを呼んで閉じる。
"""
import json
import os

from muse_code import MuseClientSpawnOptions, SyncMuseClient

client = SyncMuseClient.spawn(
    MuseClientSpawnOptions(
        muse_bin=os.environ["MUSE_BIN_PATH"],
        args=["serve"],
        client_info={"name": "muse_lib_sdk_profiles", "version": "1.0.0"},
        capabilities={"experimentalApi": True},
    )
)
try:
    profiles = client.command("permissionProfile/list", {})
    print(json.dumps({"permissionProfiles": profiles}, ensure_ascii=False, indent=2))
    try:
        models = client.list_models()
        print(json.dumps({"models": models}, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        print(f"list_models failed: {exc}")
finally:
    client.close()
