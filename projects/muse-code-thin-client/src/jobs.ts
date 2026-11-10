import { DurableObject } from 'cloudflare:workers';
import type { Env } from './types';
import type { CodeInput, CodeResult } from './transport';

type Row = { id: string; prompt: string; state: string; result: string | null; created_at: string };
export function parseInput(data: unknown): CodeInput | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  if (typeof d.requestId !== 'string' || !/^[a-zA-Z0-9-]{1,64}$/.test(d.requestId) ||
      typeof d.prompt !== 'string' || !d.prompt.trim() || new TextEncoder().encode(d.prompt).length > 16384 ||
      Object.keys(d).some(k => !['requestId', 'prompt'].includes(k))) return null;
  return { requestId: d.requestId, prompt: d.prompt };
}
/** Separate durable ledger; borrowed from deployed MuseAgentJobs claim/unknown semantics. */
export class CodeJobs extends DurableObject<Env> {
  private busy = false;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, prompt TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL)');
      ctx.storage.sql.exec("UPDATE jobs SET state='delivery_unknown', result=? WHERE state='sending'",
        JSON.stringify({ status: 'delivery_unknown', error: 'worker_restarted_after_dispatch' }));
      if ([...ctx.storage.sql.exec("SELECT id FROM jobs WHERE state='queued' LIMIT 1")].length) await ctx.storage.setAlarm(Date.now() + 1000);
    });
  }
  private view(row: Row) { return { requestId: row.id, status: row.state, createdAt: row.created_at,
    ...(row.result ? { result: JSON.parse(row.result) } : {}) }; }
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/jobs' && request.method === 'POST') {
      let input: CodeInput | null;
      try { input = parseInput(await request.json()); } catch { input = null; }
      if (!input) return Response.json({ error: 'invalid_request' }, { status: 400 });
      let row: Row;
      let conflict = false;
      this.ctx.storage.transactionSync(() => {
        const previous = [...this.ctx.storage.sql.exec<Row>('SELECT * FROM jobs WHERE id=?', input!.requestId)][0];
        if (previous) { row = previous; conflict = previous.prompt !== input!.prompt; return; }
        this.ctx.storage.sql.exec("INSERT INTO jobs VALUES (?,?,'queued',NULL,?)", input!.requestId, input!.prompt, new Date().toISOString());
        row = [...this.ctx.storage.sql.exec<Row>('SELECT * FROM jobs WHERE id=?', input!.requestId)][0];
      });
      if (conflict) return Response.json({ error: 'request_id_conflict' }, { status: 409 });
      if (row!.state === 'queued' && !this.busy) await this.ctx.storage.setAlarm(Date.now() + 50);
      return Response.json(this.view(row!), { status: row!.state === 'queued' ? 202 : 200 });
    }
    if (request.method === 'GET' && /^\/jobs\/[a-zA-Z0-9-]{1,64}$/.test(url.pathname)) {
      const row = [...this.ctx.storage.sql.exec<Row>('SELECT * FROM jobs WHERE id=?', url.pathname.slice(6))][0];
      return row ? Response.json(this.view(row)) : Response.json({ error: 'not_found' }, { status: 404 });
    }
    return new Response('Not found', { status: 404 });
  }
  async alarm() {
    if (this.busy) return;
    this.busy = true;
    const sql = this.ctx.storage.sql;
    const row = [...sql.exec<Row>("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at,id LIMIT 1")][0];
    try {
      if (!row) return;
      // Commit the claim before dispatch. Recovery never resends claimed work.
      sql.exec("UPDATE jobs SET state='sending' WHERE id=? AND state='queued'", row.id);
      let result: CodeResult;
      try {
        const response = await this.env.TAILNET.get(this.env.TAILNET.idFromName('sdk')).fetch('http://tailnet/code', {
          method: 'POST', body: JSON.stringify({ requestId: row.id, prompt: row.prompt }),
        });
        result = response.ok ? await response.json() : { status: 'failed', error: 'tailscale_wasm_unavailable' };
        if (!['completed', 'failed', 'delivery_unknown'].includes(result.status)) throw Error();
      } catch { result = { status: 'delivery_unknown', error: 'delivery_unconfirmed' }; }
      sql.exec('UPDATE jobs SET state=?,result=? WHERE id=?', result.status, JSON.stringify(result), row.id);
    } finally {
      this.busy = false;
      if ([...sql.exec("SELECT id FROM jobs WHERE state='queued' LIMIT 1")].length) await this.ctx.storage.setAlarm(Date.now() + 50);
    }
  }
}
