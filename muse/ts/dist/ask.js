// sdk-ask.py の TypeScript 版。Muse Code SDK で1ターンを実行する。
//
// 環境変数で受け取る: PROFILE, WORKSPACE, INSTRUCTION, JSON（sdk-ask.py と同じ約束）
// - 指定プロファイルが適用されなければ黙って落とさずエラーにする
//   （require で弾かれた場合は読み戻し確認で対処。Python 版と同じ方式）
import { PermissionProfileNotApplied } from "@muse-code/sdk";
import { spawnClient } from "./common.js";
const profile = process.env.PROFILE ?? ":auto-review";
const workspace = process.env.WORKSPACE ?? process.cwd();
const instruction = process.env.INSTRUCTION ?? "";
const asJson = process.env.JSON === "1";
const result = {
    profile,
    profile_verified: null,
    session_id: null,
    outcome: null,
    terminal: null,
    error: null,
    output: "",
};
const client = await spawnClient("muse_lib_sdk_ask_ts");
try {
    let session = null;
    try {
        session = await client.startSession({
            workspaceRoot: workspace,
            permissionProfile: profile,
            requirePermissionProfile: true,
        });
        result.profile_verified = "require";
    }
    catch (exc) {
        if (exc instanceof PermissionProfileNotApplied && String(exc).includes("unknown")) {
            // ホストが適用済みプロファイルを報告できない既知の癖。
            // 読み戻して一致した場合だけ続行する（sdk-ask.py と同じ）。
            session = await client.startSession({
                workspaceRoot: workspace,
                permissionProfile: profile,
            });
            const rawCommand = client.command.bind(client);
            const read = (await rawCommand("session/read", {
                sessionId: session.sessionId,
            }));
            const committed = read.session?.permissionState?.profileId;
            if (committed !== profile) {
                result.error = {
                    kind: "profile_not_applied",
                    message: `requested ${profile}, read-back shows ${String(committed)}`,
                };
                session = null;
            }
            else {
                result.profile_verified = "read-back";
            }
        }
        else if (exc instanceof PermissionProfileNotApplied ||
            String(exc).includes("permission profile")) {
            result.error = { kind: "profile_not_applied", message: String(exc) };
        }
        else {
            throw exc;
        }
    }
    if (session !== null) {
        result.session_id = session.sessionId;
        const run = await session.run(instruction);
        const outcome = run.outcome;
        result.outcome = outcome.kind ?? null;
        result.terminal = outcome.params?.terminal ?? null;
        const err = outcome.params?.error;
        if (err !== undefined && err !== null) {
            result.error =
                typeof err === "object" ? err : { kind: String(err) };
        }
        result.output = run.finalText ?? "";
    }
}
finally {
    await client.close();
}
if (asJson) {
    console.error(result.output);
    console.log(JSON.stringify(result, null, 2));
}
else {
    console.log(result.output);
    if (result.error !== null) {
        console.error(`error: ${JSON.stringify(result.error)}`);
    }
}
process.exit(result.error === null ? 0 : 1);
