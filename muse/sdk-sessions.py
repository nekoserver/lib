#!/usr/bin/env python3
"""sdk-sessions.sh の実体。ホストのセッション一覧と使用量を出す（読み取り専用）。"""
import json
import os

from muse_code import MuseClientSpawnOptions, SyncMuseClient

client = SyncMuseClient.spawn(
    MuseClientSpawnOptions(
        muse_bin=os.environ["MUSE_BIN_PATH"],
        args=["serve"],
        client_info={"name": "muse_lib_sdk_sessions", "version": "1.0.0"},
        capabilities={"experimentalApi": True},
    )
)
try:
    sessions = client.list_sessions()
    print(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2, default=str))
    try:
        usage = client.read_usage()
        print(json.dumps({"usage": usage}, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        print(f"read_usage failed: {exc}")
finally:
    client.close()
