// sdk-sessions.py の TypeScript 版。セッション一覧と使用量（読み取り専用）。
import { spawnClient } from "./common.js";

const client = await spawnClient("muse_lib_sdk_sessions_ts");
try {
  const sessions = await client.listSessions();
  console.log(JSON.stringify({ sessions }, null, 2));
  try {
    const usage = await client.readUsage();
    console.log(JSON.stringify({ usage }, null, 2));
  } catch (exc) {
    console.log(`readUsage failed: ${String(exc)}`);
  }
} finally {
  await client.close();
}
