import type { IPN, IPNResponse } from '@ai-ecoverse/wasm-tailscale';
export type NodeStatus = { state?: string; peers?: { name?: string; dnsName?: string; online?: boolean }[]; shieldsUp?: boolean };
type GadgetEnv = { MUSE_GADGET_SDK_TOKEN?: string; MUSE_GADGET_RELAY_URL?: string; ORIGIN_HMAC_SECRET?: string; TAILSCALE_WASM_AUTHKEY?: string; TAILSCALE_AUTHKEY?: string };
const SDK_TOKEN = /^mgst_[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/;
const hex = (bytes: ArrayBuffer) => [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, '0')).join('');
export class WasmTailnetService {
  private loginURL: string | null = null;
  constructor(private node: IPN, private env: GadgetEnv, private timeouts = { status: 20_000, chat: 300_000 }) {}
  browse(url: string) {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.username || u.password || !(u.hostname === 'login.tailscale.com' || u.hostname.endsWith('.tailscale.com'))) throw new Error('Unexpected Tailscale login URL');
    this.loginURL = u.href;
  }
  status(): NodeStatus {
    const raw = this.node.status(); if (raw instanceof Error) throw raw;
    const data = JSON.parse(raw) as NodeStatus;
    if (!data || typeof data.state !== 'string' || !Array.isArray(data.peers)) throw new Error('Invalid tailnet status');
    if (data.state === 'Running') this.loginURL = null;
    return data;
  }
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path === '/status' && request.method === 'GET') return Response.json({ ...this.status(), loginURL: this.loginURL, sdkTokenConfigured: !!this.env.MUSE_GADGET_SDK_TOKEN, sdkTokenFormatValid: SDK_TOKEN.test(this.env.MUSE_GADGET_SDK_TOKEN ?? '') });
    if (path === '/login' && request.method === 'POST') {
      let body: { authKey?: unknown };
      try { body = await request.json(); } catch { return Response.json({ error: 'invalid_json' }, { status: 400 }); }
      if (!body || typeof body !== 'object' || Array.isArray(body)) return Response.json({ error: 'invalid_json' }, { status: 400 });
      if (body.authKey !== undefined && (typeof body.authKey !== 'string' || !body.authKey.startsWith('tskey-auth-') || body.authKey.length > 512)) return Response.json({ error: 'invalid_auth_key' }, { status: 400 });
      this.loginURL = null; this.node.login(body.authKey as string | undefined ?? this.env.TAILSCALE_WASM_AUTHKEY ?? this.env.TAILSCALE_AUTHKEY); return Response.json({ requested: true });
    }
    if (path === '/logout' && request.method === 'POST') { this.loginURL = null; this.node.logout(); return Response.json({ requested: true }); }
    const health = path === '/gadget/status' && request.method === 'POST';
    const chat = path === '/gadget/chat' && request.method === 'POST';
    if (!health && !chat) return new Response('Not found', { status: 404 });
    const token = this.env.MUSE_GADGET_SDK_TOKEN;
    if (!token || !SDK_TOKEN.test(token)) return Response.json({ error: 'gadget_sdk_token_missing_or_invalid' }, { status: 503 });
    if (!this.env.ORIGIN_HMAC_SECRET || !this.env.MUSE_GADGET_RELAY_URL) return Response.json({ error: 'gadget_relay_not_configured' }, { status: 503 });
    const target = new URL(this.env.MUSE_GADGET_RELAY_URL);
    if (target.protocol !== 'http:' || target.username || target.password || target.pathname !== '/' || target.search || target.hash) return Response.json({ error: 'invalid_relay_configuration' }, { status: 503 });
    const state = this.status();
    const host = target.hostname.split('.')[0];
    if (state.state !== 'Running' || !state.peers?.some(p => (p.name?.split('.')[0] === host || p.dnsName?.split('.')[0] === host) && p.online === true)) return Response.json({ error: 'gadget_relay_offline' }, { status: 503 });
    let data: Record<string, unknown> = {};
    if (chat) {
      const raw = await request.text();
      if (new TextEncoder().encode(raw).length > 32_768) return new Response('Payload too large', { status: 413 });
      try { data = JSON.parse(raw); } catch { return Response.json({ error: 'invalid_json' }, { status: 400 }); }
      if (!data || typeof data.prompt !== 'string' || !data.prompt.trim() || new TextEncoder().encode(data.prompt).length > 16_384 || typeof data.conversationId !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(data.conversationId) || typeof data.requestId !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(data.requestId)) return new Response('Invalid message', { status: 400 });
      data = { prompt: data.prompt, conversationId: data.conversationId, requestId: data.requestId };
    }
    const body = new TextEncoder().encode(JSON.stringify({ ...data, sdkToken: token }));
    const timestamp = String(Math.floor(Date.now() / 1000));
    const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(this.env.ORIGIN_HMAC_SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const canonical = 'POST\n' + path + '\n' + timestamp + '\n' + hex(await crypto.subtle.digest('SHA-256', body));
    const signature = hex(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(canonical)));
    let upstream: IPNResponse | undefined; let expired = false; let timer: ReturnType<typeof setTimeout> | undefined;
    const execute = async () => {
      upstream = await this.node.fetch({ url: target.origin + path, method: 'POST', headers: [['Content-Type', 'application/json'], ['X-Timestamp', timestamp], ['X-Signature', signature]], body, manualRedirects: true });
      if (expired) { upstream.cancel(); throw new Error('Expired'); }
      const chunks: Uint8Array[] = []; let length = 0;
      for (;;) {
        const chunk = await upstream.read(); if (expired) throw new Error('Expired'); if (chunk === null) break;
        length += chunk.length; if (length > 1_048_576) throw new Error('Response too large'); chunks.push(chunk);
      }
      const bytes = new Uint8Array(length); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return new Response(bytes, { status: upstream.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
    };
    try { return await Promise.race([execute(), new Promise<Response>(resolve => { timer = setTimeout(() => { expired = true; upstream?.cancel(); resolve(Response.json({ error: 'gadget_timeout' }, { status: 504 })); }, health ? this.timeouts.status : this.timeouts.chat); })]); }
    catch { upstream?.cancel(); return Response.json({ error: 'gadget_connection_failed' }, { status: 502 }); }
    finally { clearTimeout(timer); }
  }
}
