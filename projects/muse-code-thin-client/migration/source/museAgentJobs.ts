import { parseCompletion } from './museDirectAsk';
const ID = /^[a-zA-Z0-9-]{1,64}$/;
type Message = { id: string; job_id: string; owner: string; agent: string; prompt: string; state: string; reply: string | null };
/** Durable work ledger. A delivery interrupted after claiming is never resent automatically. */
export class MuseAgentJobs {
  constructor(private storage: DurableObjectStorage, private send: (prompt: string) => Promise<Response>) {
    const sql = storage.sql;
    sql.exec('CREATE TABLE IF NOT EXISTS muse_agent_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL)');
    sql.exec("CREATE TABLE IF NOT EXISTS muse_agent_messages (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES muse_agent_jobs(id), owner TEXT NOT NULL, agent TEXT NOT NULL, prompt TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued', reply TEXT)");
    sql.exec('CREATE TABLE IF NOT EXISTS muse_agent_events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, message_id TEXT NOT NULL, owner TEXT NOT NULL, agent TEXT NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL)');
    sql.exec('CREATE INDEX IF NOT EXISTS muse_agent_events_owner ON muse_agent_events(owner,id)');
    sql.exec('CREATE TABLE IF NOT EXISTS muse_agent_cursors (owner TEXT NOT NULL, consumer TEXT NOT NULL, cursor INTEGER NOT NULL, PRIMARY KEY(owner,consumer))');
    storage.transactionSync(() => {
      for (const row of sql.exec<Message>("SELECT * FROM muse_agent_messages WHERE state='sending'")) {
        sql.exec("UPDATE muse_agent_messages SET state='delivery_unknown' WHERE id=?", row.id);
        this.event(row, 'delivery_unknown');
      }
    });
  }
  private event(row: Message, state: string) {
    this.storage.sql.exec('INSERT INTO muse_agent_events(job_id,message_id,owner,agent,state,at) VALUES(?,?,?,?,?,?)', row.job_id, row.id, row.owner, row.agent, state, new Date().toISOString());
  }
  async enqueue(owner: string, input: unknown): Promise<Response> {
    const data = input as { requestId?: unknown; jobId?: unknown; agent?: unknown; prompt?: unknown } | null;
    if (!data || typeof data.requestId !== 'string' || !ID.test(data.requestId) || typeof data.prompt !== 'string' || !data.prompt.trim() || new TextEncoder().encode(data.prompt).length > 16384 || data.jobId !== undefined && (typeof data.jobId !== 'string' || !ID.test(data.jobId)) || data.agent !== undefined && !['user', 'codex', 'claude'].includes(String(data.agent))) return Response.json({ error: 'invalid_job' }, { status: 400 });
    const agent = String(data.agent || 'user');
    const existing = [...this.storage.sql.exec<Message>('SELECT * FROM muse_agent_messages WHERE id=?', data.requestId)][0];
    if (existing) {
      if (existing.owner !== owner || existing.agent !== agent || existing.prompt !== data.prompt || data.jobId !== undefined && existing.job_id !== data.jobId) return Response.json({ error: 'request_id_conflict' }, { status: 409 });
      if (existing.state === 'queued') await this.storage.setAlarm(Date.now() + 1000);
      return Response.json({ ok: true, jobId: existing.job_id, messageId: existing.id, state: existing.state, duplicate: true });
    }
    const jobId = typeof data.jobId === 'string' ? data.jobId : crypto.randomUUID();
    if (data.jobId !== undefined && ![...this.storage.sql.exec('SELECT id FROM muse_agent_jobs WHERE id=? AND owner=?', jobId, owner)].length) return Response.json({ error: 'job_not_found' }, { status: 404 });
    this.storage.transactionSync(() => {
      if (data.jobId === undefined) this.storage.sql.exec('INSERT INTO muse_agent_jobs(id,owner,created_at) VALUES(?,?,?)', jobId, owner, new Date().toISOString());
      this.storage.sql.exec('INSERT INTO muse_agent_messages(id,job_id,owner,agent,prompt) VALUES(?,?,?,?,?)', data.requestId as string, jobId, owner, agent, data.prompt as string);
      this.event({ id: data.requestId, job_id: jobId, owner, agent } as Message, 'queued');
    });
    await this.storage.setAlarm(Date.now() + 1000);
    return Response.json({ ok: true, jobId, messageId: data.requestId, state: 'queued' }, { status: 202 });
  }
  async list(owner: string) {
    return [...this.storage.sql.exec<{ id: string; created_at: string }>('SELECT id,created_at FROM muse_agent_jobs WHERE owner=? ORDER BY rowid DESC LIMIT 20', owner)].map(job => ({ jobId: job.id, createdAt: job.created_at, messages: [...this.storage.sql.exec<Message>('SELECT * FROM muse_agent_messages WHERE job_id=? AND owner=? ORDER BY rowid DESC LIMIT 50', job.id, owner)].reverse().map(row => ({ messageId: row.id, agent: row.agent, prompt: row.prompt, state: row.state, reply: row.reply })) }));
  }
  async processOne() {
    const row = this.storage.transactionSync(() => {
      const row = [...this.storage.sql.exec<Message>("SELECT * FROM muse_agent_messages WHERE state='queued' ORDER BY rowid LIMIT 1")][0];
      if (!row) return null;
      this.storage.sql.exec("UPDATE muse_agent_messages SET state='sending' WHERE id=? AND state='queued'", row.id);
      this.event(row, 'sending'); return row;
    });
    if (!row) return;
    let state = 'delivery_unknown', reply: string | null = null;
    try {
      const earlier = [...this.storage.sql.exec<Message>("SELECT * FROM muse_agent_messages WHERE job_id=? AND rowid < (SELECT rowid FROM muse_agent_messages WHERE id=?) AND state='done' AND reply IS NOT NULL ORDER BY rowid", row.job_id, row.id)];
      const encoder = new TextEncoder();
      const current = `今回の依頼 (${row.agent}):\n${row.prompt}`;
      const history: string[] = [];
      let used = encoder.encode(current).length;
      const budget = 16384 - encoder.encode('同じJobの会話履歴を参考にしてください。\n').length;
      for (const previous of earlier.reverse()) {
        const turn = `\n\n以前の依頼 (${previous.agent}):\n${previous.prompt}\nMuseの回答:\n${previous.reply}`;
        const size = encoder.encode(turn).length;
        if (used + size > budget) break;
        history.unshift(turn); used += size;
      }
      const response = await this.send(history.length ? `同じJobの会話履歴を参考にしてください。\n${history.join('')}\n\n${current}` : row.prompt);
      if (response.status === 200) {
        const result = parseCompletion(await response.text());
        if (result.ok) { state = 'done'; reply = result.reply; }
      } else if ([400, 401, 403, 404, 413, 429, 503].includes(response.status)) state = 'failed';
    } catch { /* Unknown delivery is recorded and never automatically retried. */ }
    this.storage.transactionSync(() => {
      this.storage.sql.exec('UPDATE muse_agent_messages SET state=?,reply=? WHERE id=?', state, reply, row.id);
      this.event(row, state);
    });
    if ([...this.storage.sql.exec("SELECT id FROM muse_agent_messages WHERE state='queued' LIMIT 1")].length) await this.storage.setAlarm(Date.now() + 1000);
  }
  async changes(owner: string, consumer: string) {
    const cursor = [...this.storage.sql.exec<{ cursor: number }>('SELECT cursor FROM muse_agent_cursors WHERE owner=? AND consumer=?', owner, consumer)][0]?.cursor || 0;
    const events = [...this.storage.sql.exec<{ id: number; jobId: string; messageId: string; agent: string; state: string; at: string; prompt: string; reply: string | null }>(`SELECT e.id,e.job_id AS jobId,e.message_id AS messageId,e.agent,e.state,e.at,m.prompt,m.reply FROM muse_agent_events e JOIN muse_agent_messages m ON m.id=e.message_id WHERE e.owner=? AND e.id>? ORDER BY e.id LIMIT 100`, owner, cursor)];
    return { consumer, acknowledgedCursor: cursor, cursor: events.at(-1)?.id || cursor, events };
  }
  async ack(owner: string, consumer: string, cursor: unknown): Promise<Response> {
    if (!['codex', 'claude'].includes(consumer) || !Number.isSafeInteger(cursor) || Number(cursor) < 0) return Response.json({ error: 'invalid_cursor' }, { status: 400 });
    const maximum = [...this.storage.sql.exec<{ maximum: number }>('SELECT COALESCE(MAX(id),0) AS maximum FROM muse_agent_events WHERE owner=?', owner)][0].maximum;
    if (Number(cursor) > maximum) return Response.json({ error: 'invalid_cursor' }, { status: 400 });
    this.storage.sql.exec('INSERT INTO muse_agent_cursors(owner,consumer,cursor) VALUES(?,?,?) ON CONFLICT(owner,consumer) DO UPDATE SET cursor=MAX(cursor,excluded.cursor)', owner, consumer, Number(cursor));
    return Response.json({ ok: true, consumer, cursor: [...this.storage.sql.exec<{ cursor: number }>('SELECT cursor FROM muse_agent_cursors WHERE owner=? AND consumer=?', owner, consumer)][0].cursor });
  }
}
