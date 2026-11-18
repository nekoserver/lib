import type { IPN, IPNResponse } from '@ai-ecoverse/wasm-tailscale';

export type CodeInput = { requestId: string; prompt: string };
export type CodeResult = {
  status: 'completed' | 'failed' | 'delivery_unknown';
  terminal?: string;
  reply?: string;
  error?: string;
  sessionId?: string;
  turnId?: string;
};
export type TargetEnv = { SDK_TARGET_URL?: string; SDK_API_TOKEN?: string };
type Node = Pick<IPN, 'status' | 'fetch'>;
const encoder = new TextEncoder();

/** Migration of the deployed WasmMuseBridge transport; SDK result contract is new. */
export class SdkTransport {
  node: Node;
  env: TargetEnv;
  timeoutMs: number;
  constructor(node: Node, env: TargetEnv, timeoutMs = 130_000) {
    this.node = node; this.env = env; this.timeoutMs = timeoutMs;
  }
  async run(input: CodeInput): Promise<CodeResult> {
    let target: URL;
    try {
      target = new URL(this.env.SDK_TARGET_URL ?? '');
      if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password ||
          target.search || target.hash || target.pathname !== '/agent/code/run' ||
          !/^[a-z0-9-]+(?:\.[a-z0-9-]+\.ts\.net)?$/i.test(target.hostname)) throw Error();
    } catch { return { status: 'failed', error: 'sdk_target_not_configured' }; }
    if (!this.env.SDK_API_TOKEN) return { status: 'failed', error: 'sdk_auth_not_configured' };
    try {
      const raw = this.node.status();
      if (raw instanceof Error || JSON.parse(raw).state !== 'Running') {
        return { status: 'failed', error: 'tailscale_not_connected' };
      }
    } catch { return { status: 'failed', error: 'tailscale_not_connected' }; }

    // Caller never chooses destination, credential, workspace, model, or permissions.
    let upstream: IPNResponse | undefined;
    let expired = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const execute = async (): Promise<CodeResult> => {
      upstream = await this.node.fetch({
        url: target.href, method: 'POST', manualRedirects: true,
        headers: [['Content-Type', 'application/json'], ['Authorization', 'Bearer ' + this.env.SDK_API_TOKEN]],
        body: encoder.encode(JSON.stringify(input)),
      });
      if (expired) { upstream.cancel(); return { status: 'delivery_unknown', error: 'transport_timeout' }; }
      const chunks: Uint8Array[] = [];
      let size = 0;
      for (;;) {
        const chunk = await upstream.read();
        if (expired) return { status: 'delivery_unknown', error: 'transport_timeout' };
        if (chunk === null) break;
        size += chunk.length;
        if (size > 1_048_576) throw Error('response_limit');
        chunks.push(chunk);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
      const data = JSON.parse(new TextDecoder().decode(bytes));
      const safeError = typeof data.error === 'string' && /^[a-z_]{1,80}$/.test(data.error) ? data.error : 'sdk_execution_failed';
      if ([401, 403, 409, 422, 429].includes(upstream.status)) return { status: 'failed', error: safeError };
      if (data.requestId !== input.requestId) return { status: 'delivery_unknown', error: 'sdk_response_unconfirmed' };
      if (upstream.status === 200 && data.status === 'completed' && data.terminal === 'completed' && typeof data.reply === 'string') {
        return { status: 'completed', terminal: 'completed', reply: data.reply,
          ...(typeof data.sessionId === 'string' ? { sessionId: data.sessionId } : {}),
          ...(typeof data.turnId === 'string' ? { turnId: data.turnId } : {}) };
      }
      if (data.status === 'failed') return { status: 'failed', error: safeError };
      return { status: 'delivery_unknown', error: 'sdk_response_unconfirmed' };
    };
    try {
      return await Promise.race([execute(), new Promise<CodeResult>(resolve => {
        timer = setTimeout(() => {
          expired = true; upstream?.cancel();
          resolve({ status: 'delivery_unknown', error: 'transport_timeout' });
        }, this.timeoutMs);
      })]);
    } catch { upstream?.cancel(); return { status: 'delivery_unknown', error: 'transport_disconnected' }; }
    finally { clearTimeout(timer); }
  }
}
