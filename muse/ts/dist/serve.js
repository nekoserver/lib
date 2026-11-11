// sdk-serve.sh の TypeScript 版。muse serve のソケットデーモン（--listen）を管理する。
// 状態ディレクトリは sh 版と共通（~/.local/share/muse-serve）なので、
// どちらからでも同じデーモンを制御できる。
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { museBin } from "./common.js";
const STATE = join(homedir(), ".local/share/muse-serve");
const SOCK = join(homedir(), ".local/share/muse/session-server/session-server.sock");
const PIDFILE = join(STATE, "serve.pid");
const LOG = join(STATE, "serve.log");
function runningPid() {
    if (!existsSync(PIDFILE))
        return null;
    const pid = Number(readFileSync(PIDFILE, "utf-8").trim());
    if (!pid)
        return null;
    try {
        process.kill(pid, 0);
        return pid;
    }
    catch {
        return null;
    }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cmd = process.argv[2];
if (cmd === "start") {
    const existing = runningPid();
    if (existing !== null) {
        console.log(`already running (PID ${existing})`);
    }
    else {
        mkdirSync(STATE, { recursive: true });
        const out = openSync(LOG, "a");
        const child = spawn(museBin(), ["serve", "--listen"], {
            detached: true,
            stdio: ["ignore", out, out],
        });
        child.unref();
        writeFileSync(PIDFILE, `${child.pid}\n`);
        for (let i = 0; i < 20 && !existsSync(SOCK); i++) {
            if (runningPid() === null) {
                console.error(`起動に失敗しました。ログ: ${LOG}`);
                process.exit(1);
            }
            await sleep(500);
        }
        console.log(`started (PID ${child.pid}, socket: ${SOCK})`);
    }
}
else if (cmd === "stop") {
    const pid = runningPid();
    if (pid !== null) {
        process.kill(pid);
        rmSync(PIDFILE, { force: true });
        console.log("stopped");
    }
    else {
        console.log("not running");
    }
}
else if (cmd === "status") {
    const pid = runningPid();
    console.log(pid !== null ? `running (PID ${pid}, socket: ${SOCK})` : "not running");
}
else {
    console.error("usage: serve {start|stop|status}");
    process.exit(64);
}
