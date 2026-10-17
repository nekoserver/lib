import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, createHash, webcrypto } from 'node:crypto';
import { parseStream, HttpStream } from '../chat/http-stream.mjs';

const events = [{ type: 'delta', text: '日本語\n改行' }, { type: 'job', ask_status: 'done', reply: '完了' }];
const wire = (protocol, messages = events) => messages.map(event => {
  const data = JSON.stringify(event);
  return protocol === 'sse' ? `event: ${event.type}\ndata: ${data}\n\n` : protocol === 'jsonseq' ? `\x1e${data}\n` : data + '\n';
}).join('');
function body(text, byteByByte = false) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({ start(controller) {
    if (byteByByte) for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    else controller.enqueue(bytes);
    controller.close();
  } });
}

for (const protocol of ['sse', 'ndjson', 'jsonseq']) {
  test(`${protocol}: fragmented UTF-8 and multiple records are preserved`, async () => {
    for (const fragmented of [true, false]) {
      const actual = [];
      for await (const event of parseStream(body(wire(protocol), fragmented), protocol)) actual.push(event);
      assert.deepEqual(actual, events);
    }
  });
  test(`${protocol}: signs the exact POST path and body, submits once`, async () => {
    const calls = [], updates = [];
    const client = new HttpStream(protocol, { crypto: webcrypto, fetch: async (path, options) => {
      calls.push(options);
      const canonical = `POST\n${path}\n${options.headers['X-Timestamp']}\n${createHash('sha256').update(options.body).digest('hex')}`;
      assert.equal(options.headers['X-Signature'], createHmac('sha256', 'key').update(canonical).digest('hex'));
      return new Response(body(wire(protocol)), { headers: { 'content-type': { sse: 'text/event-stream', ndjson: 'application/x-ndjson', jsonseq: 'application/json-seq' }[protocol] } });
    } });
    await client.watch('  key \n', { type: 'resume', ask_id: 'existing' }, event => updates.push(event));
    assert.equal(calls.length, 1);
    assert.equal(JSON.parse(calls[0].body).type, 'resume');
    assert.deepEqual(updates, events);
  });
}

test('SSE parses CRLF, comments, IDs and multiline data', async () => {
  const stream = ': heartbeat\r\n\r\nid: 1\r\nevent: delta\r\ndata: {"type":"delta",\r\ndata: "text":"yes"}\r\n\r\n';
  const result = [];
  for await (const event of parseStream(body(stream, true), 'sse')) result.push(event);
  assert.deepEqual(result, [{ type: 'delta', text: 'yes' }]);
});

test('JSON-seq supports formatted multiline JSON', async () => {
  const result = [];
  for await (const event of parseStream(body('\x1e{\n"type":"heartbeat"\n}\n', true), 'jsonseq')) result.push(event);
  assert.deepEqual(result, [{ type: 'heartbeat' }]);
});

test('truncated HTTP streams do not silently succeed', async () => {
  for (const protocol of ['sse', 'ndjson', 'jsonseq']) {
    const client = new HttpStream(protocol, { fetch: async () => new Response(body(wire(protocol, [events[0]])), { headers: { 'content-type': { sse: 'text/event-stream', ndjson: 'application/x-ndjson', jsonseq: 'application/json-seq' }[protocol] } }) });
    await assert.rejects(client.watch('', { type: 'demo' }, () => {}), /接続が切れ/);
  }
});

test('stopping an HTTP stream aborts without another request', async () => {
  let calls = 0;
  const client = new HttpStream('sse', { fetch: async (_path, { signal }) => {
    calls++;
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new DOMException('stopped', 'AbortError'))));
  } });
  const pending = client.watch('', { type: 'demo' }, () => {});
  const assertion = assert.rejects(pending, /受信を停止/);
  client.cancel();
  await assertion;
  assert.equal(calls, 1);
});

for (const protocol of ['sse', 'ndjson', 'jsonseq']) {
  test(`${protocol}: observation session reconnects without importing an empty HMAC key`, async () => {
    let used = false;
    const client = new HttpStream(protocol, {
      crypto: { subtle: { importKey() { throw new Error('empty key imported'); } } },
      fetch: async (path, options) => {
        used = true;
        assert.equal(options.headers.Authorization, 'Bearer observer-token');
        assert.equal(options.headers['X-Signature'], undefined);
        return new Response(body(wire(protocol, [{ type: 'conversation', messages: [] }])), { headers: { 'Content-Type': ({sse:'text/event-stream',ndjson:'application/x-ndjson',jsonseq:'application/json-seq'})[protocol] } });
      },
    });
    const updates = [];
    await assert.rejects(client.watch('', { type: 'observe' }, event => updates.push(event), 'observer-token'), /接続が切れ/);
    assert.equal(used, true);
    assert.equal(updates[0].type, 'conversation');
  });
}
