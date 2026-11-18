import {parseMuseMessages} from './museMessages';
import type { IPN, IPNResponse } from '@ai-ecoverse/wasm-tailscale';

/** Private DO endpoint: no caller-selected destination, credentials or redirects. */
export class WasmMuseBridge {
  constructor(private node: IPN, private apiKey?: string, private timeoutMs = 300_000) {}
  async fetch(request: Request): Promise<Response> {
    const path = new URL(request.url).pathname;
    const health = path === '/muse/health' && request.method === 'GET';
    const chat = path === '/muse/v1/chat/completions' && request.method === 'POST';
    if (!health && !chat) return new Response('Not found', { status: 404 });
    if (!this.apiKey) return Response.json({ error: 'muse_not_authenticated' }, { status: 503 });
    const raw = this.node.status();
    if (raw instanceof Error) return Response.json({ error: 'tailscale_not_connected' }, { status: 503 });
    const state = JSON.parse(raw);
    if (state.state !== 'Running' || !state.peers?.some((p: { name?: string; dnsName?: string; online?: boolean }) => (p.name || p.dnsName || '').split('.')[0] === 'muse-vm' && p.online === true)) return Response.json({ error: 'tailscale_not_connected' }, { status: 503 });
    let body: Uint8Array | undefined;
    if (chat) {
      const text = await request.text();
      if (new TextEncoder().encode(text).length > 100000) return Response.json({ error: 'payload_too_large' }, { status: 413 });
      let data;
      try { data = JSON.parse(text); } catch { return Response.json({ error: 'invalid_prompt' }, { status: 400 }); }
      const messages = parseMuseMessages(data?.messages);
      if (!messages) return Response.json({ error: 'invalid_prompt' }, { status: 400 });
      body = new TextEncoder().encode(JSON.stringify({ model: 'muse', stream: false, messages }));
    }
    let upstream: IPNResponse | undefined, expired = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      upstream = await this.node.fetch({ url: 'http://muse-vm:8080' + (health ? '/health' : '/v1/chat/completions'), method: health ? 'GET' : 'POST', manualRedirects: true, headers: [['Authorization', 'Bearer ' + this.apiKey], ['Content-Type', 'application/json']], ...(body ? { body } : {}) });
      if (expired) { upstream.cancel(); throw new Error('expired'); }
      const chunks: Uint8Array[] = []; let size = 0;
      for (;;) {
        const chunk = await upstream.read();
        if (expired) throw new Error('expired');
        if (chunk === null) break;
        size += chunk.length;
        if (size > 1048576) throw new Error('response too large');
        chunks.push(chunk);
      }
      const bytes = new Uint8Array(size); let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      return new Response(bytes, { status: upstream.status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
    };
    try { return await Promise.race([run(), new Promise<Response>(resolve => { timer = setTimeout(() => { expired = true; upstream?.cancel(); resolve(Response.json({ error: 'llm_timeout' }, { status: 504 })); }, health ? Math.min(8000, this.timeoutMs) : this.timeoutMs); })]); }
    catch { upstream?.cancel(); return Response.json({ error: 'muse_connection_failed' }, { status: 502 }); }
    finally { clearTimeout(timer); }
  }
}
