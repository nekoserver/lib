const streamError = (message, code) => Object.assign(new Error(message), { code });
const CONTENT_TYPES = { sse: 'text/event-stream', ndjson: 'application/x-ndjson', jsonseq: 'application/json-seq' };
const hex = value => [...new Uint8Array(value)].map(b => b.toString(16).padStart(2, '0')).join('');

// Network chunks need not align with UTF-8 characters, JSON records, or SSE events.
export async function* parseStream(body, protocol) {
  if (!(protocol in CONTENT_TYPES)) throw new Error('未対応の通信方式です。');
  const reader = body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  function take(final) {
    const events = [];
    if (protocol === 'sse') {
      buffer = buffer.replace(/\r\n/g, '\n').replace(/\r(?!$)/g, '\n');
      if (final) buffer = buffer.replace(/\r$/, '\n');
      let end;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const lines = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, ''));
        if (lines.length) events.push(JSON.parse(lines.join('\n')));
      }
    } else if (protocol === 'ndjson') {
      let end;
      while ((end = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, end).trim();
        buffer = buffer.slice(end + 1);
        if (line) events.push(JSON.parse(line));
      }
    } else {
      while (buffer.length) {
        if (!buffer.startsWith('\x1e')) throw new Error('JSON Sequenceの区切りが不正です。');
        const next = buffer.indexOf('\x1e', 1);
        if (next !== -1) {
          events.push(JSON.parse(buffer.slice(1, next).trim()));
          buffer = buffer.slice(next);
        } else if (buffer.endsWith('\n') || final) {
          try {
            events.push(JSON.parse(buffer.slice(1).trim()));
            buffer = '';
          } catch (error) { if (final) throw error; else break; }
        } else break;
      }
    }
    if (buffer.length > 262144) throw new Error('受信イベントが大きすぎます。');
    if (final && buffer.trim()) throw new Error('ストリームが途中で切れました。');
    return events;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      for (const event of take(done)) yield event;
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export class HttpStream {
  constructor(protocol, { fetch = globalThis.fetch, crypto = globalThis.crypto } = {}) {
    this.protocol = protocol;
    this.fetch = fetch.bind(globalThis);
    this.crypto = crypto;
    this.controller = null;
  }

  cancel() { this.controller?.abort(); }

  async watch(secret, request, onUpdate, sessionToken = null) {
    if (this.controller) throw new Error('すでに接続中です。');
    const controller = new AbortController();
    this.controller = controller;
    const timer = request.type === 'observe' ? null : setTimeout(() => controller.abort(), 325000);
    try {
      const path = `/lib/api/chat/${this.protocol}`, body = JSON.stringify(request);
      const headers = { 'Content-Type': 'application/json', Accept: CONTENT_TYPES[this.protocol] };
      if (sessionToken && request.type === 'observe') headers.Authorization = 'Bearer ' + sessionToken;
      else if (request.type !== 'demo') {
        const enc = new TextEncoder(), timestamp = String(Math.floor(Date.now() / 1000));
        const key = await this.crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
        secret = '';
        const hash = hex(await this.crypto.subtle.digest('SHA-256', enc.encode(body)));
        headers['X-Timestamp'] = timestamp;
        headers['X-Signature'] = hex(await this.crypto.subtle.sign('HMAC', key, enc.encode(`POST\n${path}\n${timestamp}\n${hash}`)));
      }
      const response = await this.fetch(path, { method: 'POST', headers, body, signal: controller.signal, cache: 'no-store' });
      if (response.status === 401 && sessionToken) onUpdate({ type: 'session_expired' });
      if (!response.ok) throw streamError(response.status === 401 ? '認証に失敗しました。HMACキーを確認してください。' : `接続できませんでした（HTTP ${response.status}）。`, response.status === 401 ? 'auth_rejected' : response.status >= 500 ? 'disconnected' : 'invalid_request');
      if (!response.headers.get('content-type')?.startsWith(CONTENT_TYPES[this.protocol])) throw new Error('ストリームの種類が不正です。');
      let terminal = false;
      for await (const event of parseStream(response.body, this.protocol)) {
        if (event.type === 'error') throw streamError(({ worker_unavailable: 'AI実行サーバーに接続できません。', connection_timeout: '接続がタイムアウトしました。結果に再接続してください。' })[event.error] || 'サーバーでエラーが発生しました。', event.error);
        if (!['job', 'delta', 'info', 'heartbeat', 'conversation'].includes(event.type)) throw new Error('応答が不正です。');
        onUpdate(event);
        if (event.type === 'job' && !['pending', 'running'].includes(event.ask_status)) { terminal = true; break; }
      }
      if (!terminal) throw streamError('接続が切れました。「結果に再接続」で確認できます。', 'disconnected');
    } catch (error) {
      if (error.name === 'AbortError') throw streamError('受信を停止しました。', 'stopped');
      throw error;
    } finally {
      secret = '';
      clearTimeout(timer);
      this.controller = null;
    }
  }
}
