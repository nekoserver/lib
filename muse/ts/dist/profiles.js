// sdk-profiles.py の TypeScript 版。権限プロファイル一覧とモデル一覧（読み取り専用）。
import { spawnClient } from "./common.js";
const client = await spawnClient("muse_lib_sdk_profiles_ts");
try {
    // TS 版の command() の型ユニオンには permissionProfile/list が含まれないため、
    // Python 版と同じ汎用コマンドとして呼ぶ（実行時のメソッド名は同一）。
    const rawCommand = client.command.bind(client);
    const profiles = await rawCommand("permissionProfile/list", {});
    console.log(JSON.stringify({ permissionProfiles: profiles }, null, 2));
    try {
        const models = await client.listModels();
        console.log(JSON.stringify({ models }, null, 2));
    }
    catch (exc) {
        console.log(`listModels failed: ${String(exc)}`);
    }
}
finally {
    await client.close();
}
