// sdk-health.sh の TypeScript 版。SDK 連携の前提確認（読み取り専用）。
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { museBin } from "./common.js";

console.log("== muse 本体 ==");
const bin = museBin();
console.log(`path: ${bin}`);
try {
  process.stdout.write(execFileSync(bin, ["--version"], { encoding: "utf-8" }));
} catch {
  console.log("version: (取得できませんでした)");
}

console.log("== SDK ==");
console.log(`node: ${process.version}`);
try {
  const here = dirname(fileURLToPath(import.meta.url));
  const pkg = JSON.parse(
    readFileSync(join(here, "../node_modules/@muse-code/sdk/package.json"), "utf-8"),
  ) as { version: string };
  console.log(`@muse-code/sdk: ${pkg.version}`);
} catch {
  console.log("@muse-code/sdk: not installed (run sdk-ts-setup.sh)");
}

console.log("== 認証 ==");
console.log(
  process.env.META_API_KEY
    ? "META_API_KEY: set"
    : "META_API_KEY: not set（ブラウザサインイン側の状態はここでは分からない）",
);
console.log(`profile (MUSE_PROFILE): ${process.env.MUSE_PROFILE ?? ":auto-review (default)"}`);

console.log("== serve デーモン ==");
const state = join(homedir(), ".local/share/muse-serve");
const pidfile = join(state, "serve.pid");
let running = false;
let pid = "";
if (existsSync(pidfile)) {
  pid = readFileSync(pidfile, "utf-8").trim();
  try {
    process.kill(Number(pid), 0);
    running = true;
  } catch {
    running = false;
  }
}
console.log(
  running
    ? `running (PID ${pid}, socket: ~/.local/share/muse/session-server/session-server.sock)`
    : "not running",
);
