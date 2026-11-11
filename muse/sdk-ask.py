#!/usr/bin/env python3
"""sdk-ask.sh の実体。Muse Code SDK（同期ファサード）で1ターンを実行する。

環境変数で受け取る: MUSE_BIN_PATH, PROFILE, WORKSPACE, INSTRUCTION, JSON
- 指定プロファイルが適用されなければ黙って落とさずエラーにする
  （require で弾かれた場合の「報告だけできない」癖には読み戻し確認で対処）
"""
import json
import os
import sys

from muse_code import (
    MuseClientSpawnOptions,
    PermissionProfileNotApplied,
    StartSessionOptions,
    SyncMuseClient,
)

profile = os.environ["PROFILE"]
workspace = os.environ["WORKSPACE"]
instruction = os.environ["INSTRUCTION"]
as_json = os.environ.get("JSON") == "1"

result = {
    "profile": profile,
    "profile_verified": None,
    "session_id": None,
    "outcome": None,
    "terminal": None,
    "error": None,
    "output": "",
}

client = SyncMuseClient.spawn(
    MuseClientSpawnOptions(
        muse_bin=os.environ["MUSE_BIN_PATH"],
        args=["serve"],
        client_info={"name": "muse_lib_sdk_ask", "version": "1.0.0"},
        capabilities={"experimentalApi": True},
    )
)
try:
    session = None
    try:
        session = client.start_session(
            StartSessionOptions(
                workspace_root=workspace,
                permission_profile=profile,
                require_permission_profile=True,
            )
        )
        result["profile_verified"] = "require"
    except PermissionProfileNotApplied as exc:
        if "unknown" not in str(exc):
            result["error"] = {"kind": "profile_not_applied", "message": str(exc)}
        else:
            # ホストが適用済みプロファイルを報告できない既知の癖。
            # 読み戻して一致した場合だけ続行する。
            session = client.start_session(
                StartSessionOptions(workspace_root=workspace, permission_profile=profile)
            )
            read = client.command("session/read", {"sessionId": session.session_id})
            committed = (read.get("session", {}).get("permissionState", {}) or {}).get(
                "profileId"
            )
            if committed != profile:
                result["error"] = {
                    "kind": "profile_not_applied",
                    "message": f"requested {profile}, read-back shows {committed!r}",
                }
                session = None
            else:
                result["profile_verified"] = "read-back"
    except Exception as exc:
        if "permission profile" in str(exc):
            result["error"] = {"kind": "profile_not_applied", "message": str(exc)}
        else:
            raise
    if session is not None:
        result["session_id"] = session.session_id
        run = session.run(instruction)
        outcome = run.outcome
        result["outcome"] = getattr(outcome, "kind", None)
        params = getattr(outcome, "params", None) or {}
        result["terminal"] = params.get("terminal")
        err = params.get("error")
        if err is not None:
            result["error"] = err if isinstance(err, dict) else {"kind": str(err)}
        result["output"] = run.final_text or ""
finally:
    client.close()

if as_json:
    print(result["output"], file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
else:
    print(result["output"])
    if result["error"] is not None:
        print(f"error: {json.dumps(result['error'], ensure_ascii=False)}", file=sys.stderr)

sys.exit(0 if result["error"] is None else 1)
