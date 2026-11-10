// 共通: muse 本体の解決と SDK クライアントの起動。
// Python 版（sdk-common.sh / sdk-*.py）と環境変数の約束を揃えている。
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { MuseClient } from "@muse-code/sdk";
export function museBin() {
    const fromEnv = process.env.MUSE_BIN ?? process.env.MUSE_BIN_PATH;
    if (fromEnv)
        return fromEnv;
    const local = join(homedir(), ".local/bin/muse");
    if (existsSync(local))
        return local;
    return "muse";
}
export async function spawnClient(name) {
    return MuseClient.spawn({
        museBin: museBin(),
        args: ["serve"],
        clientInfo: { name, version: "1.0.0" },
        capabilities: { experimentalApi: true },
    });
}
