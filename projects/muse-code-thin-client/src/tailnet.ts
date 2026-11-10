import { DurableObject } from 'cloudflare:workers';
import '@ai-ecoverse/wasm-tailscale/wasm_exec.js';
import wasm from '@ai-ecoverse/wasm-tailscale/main.wasm';
import type { IPN } from '@ai-ecoverse/wasm-tailscale';
import type { Env } from './types';
import { SdkTransport } from './transport';

// Ported from the running TailscaleWasm DO; only one Go runtime is imported.
let ready: Promise<void> | undefined;
async function startGo(): Promise<void> {
  return ready ??= (async () => {
    const go = new Go();
    const instance = new WebAssembly.Instance(wasm, go.importObject);
    let failure: unknown;
    void go.run(instance).catch(error => { failure = error; });
    for (let i = 0; i < 500 && typeof globalThis.newIPN !== 'function'; i++) {
      if (failure) throw Error('wasm_startup_failed');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    if (typeof globalThis.newIPN !== 'function') throw Error('wasm_startup_timeout');
  })();
}
export class ThinTailnet extends DurableObject<Env> {
  private node?: IPN;
  private nodeReady?: Promise<void>;
  private loginURL: string | null = null;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec('CREATE TABLE IF NOT EXISTS tailnet_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
  }
  private async ensureNode(): Promise<IPN> {
    await (this.nodeReady ??= (async () => {
      await startGo();
      const sql = this.ctx.storage.sql;
      const node = globalThis.newIPN({ hostname: 'muse-code-thin-client', ephemeral: false, logUpload: false, stateStorage: {
        getState(key) { return [...sql.exec<{value: string}>('SELECT value FROM tailnet_state WHERE key=?', key)][0]?.value ?? ''; },
        setState(key, value) { sql.exec('INSERT INTO tailnet_state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', key, value); },
      } });
      if (node instanceof Error) throw Error('wasm_node_failed');
      this.node = node;
      node.run({ notifyState() {}, notifyNetMap() {}, notifyPanicRecover() {}, notifyBrowseToURL: raw => {
        try {
          const u = new URL(raw);
          if (u.protocol === 'https:' && !u.username && !u.password &&
              (u.hostname === 'login.tailscale.com' || u.hostname.endsWith('.tailscale.com'))) this.loginURL = u.href;
        } catch { /* Unrecognized login URL is never displayed. */ }
      } });
    })());
    return this.node!;
  }
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    try {
      const node = await this.ensureNode();
      if (path === '/status' && request.method === 'GET') {
        const raw = node.status();
        if (raw instanceof Error) throw raw;
        const s = JSON.parse(raw);
        return Response.json({ state: s.state, shieldsUp: s.shieldsUp, loginURL: s.state === 'Running' ? null : this.loginURL,
          sdkTargetConfigured: !!this.env.SDK_TARGET_URL, sdkTokenConfigured: !!this.env.SDK_API_TOKEN });
      }
      if (path === '/login' && request.method === 'POST') {
        node.login(this.env.TAILSCALE_WASM_AUTHKEY);
        return Response.json({ requested: true });
      }
      if (path === '/logout' && request.method === 'POST') {
        node.logout(); this.loginURL = null;
        return Response.json({ requested: true });
      }
      if (path === '/code' && request.method === 'POST') {
        return Response.json(await new SdkTransport(node, this.env).run(await request.json()));
      }
      return new Response('Not found', { status: 404 });
    } catch { return Response.json({ error: 'tailscale_wasm_unavailable' }, { status: 503 }); }
  }
}
