import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto, createHmac, createHash } from 'node:crypto';

test('a reopened tab restores the cookie session without keeping the HMAC key', async () => {
  const previous = { fetch: globalThis.fetch, crypto: globalThis.crypto, sessionStorage: globalThis.sessionStorage };
  const storage = new Map(), calls = [];
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  globalThis.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key,value) => storage.set(key,value), removeItem: key => storage.delete(key) };
  globalThis.fetch = async (path, options = {}) => {
    calls.push({ path, options });
    return new Response(JSON.stringify({ token: 'readonly-cookie-session', expires_in: options.method === 'POST' ? 604800 : 518400 }));
  };
  try {
    const first = await import('../chat/session.mjs?cookie-test-first');
    await first.startSession('  test-hmac-secret \n');
    const options = calls[0].options;
    const canonical = `POST\n/lib/api/chat/session\n${options.headers['X-Timestamp']}\n${createHash('sha256').update(options.body).digest('hex')}`;
    assert.equal(options.headers['X-Signature'], createHmac('sha256', 'test-hmac-secret').update(canonical).digest('hex'));
    assert.equal(await first.sessionForKey(''), 'readonly-cookie-session');
    assert.equal(await first.sessionForKey('replacement-key'), null);
    assert.equal(first.getSession(), null);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.credentials, 'same-origin');
    assert.ok(calls[0].options.headers['X-Signature']);
    assert.ok(!JSON.stringify([...storage]).includes('test-hmac-secret'));
    storage.clear(); // Closing a tab discards sessionStorage; the browser cookie remains.
    const reopened = await import('../chat/session.mjs?cookie-test-reopened');
    const tokens = await Promise.all([reopened.restoreSession(), reopened.restoreSession()]);
    assert.deepEqual(tokens, ['readonly-cookie-session', 'readonly-cookie-session']);
    assert.equal(calls.length, 2);
    assert.equal(calls[1].options.method, undefined);
    assert.equal(calls[1].options.credentials, 'same-origin');
    assert.equal(calls[1].options.headers, undefined);
    assert.equal(reopened.getSession(), 'readonly-cookie-session');
    reopened.clearSession();
    assert.equal(calls.at(-1).options.method, 'DELETE');
  } finally {
    globalThis.fetch = previous.fetch;
    Object.defineProperty(globalThis, 'crypto', { value: previous.crypto, configurable: true });
    globalThis.sessionStorage = previous.sessionStorage;
  }
});

test('a rejected remembered session is cleared instead of hiding the key input', async () => {
  const previous = { fetch: globalThis.fetch, sessionStorage: globalThis.sessionStorage };
  const storage = new Map([['conversation-observer-session-v1', JSON.stringify({token:'old-session',expires:Date.now()+60000})]]);
  globalThis.sessionStorage = { getItem:key=>storage.get(key)??null, setItem:(key,value)=>storage.set(key,value), removeItem:key=>storage.delete(key) };
  globalThis.fetch = async () => new Response('{}', {status:401});
  try {
    const session = await import('../chat/session.mjs?cookie-test-rejected');
    assert.equal(await session.restoreSession(), null);
    assert.equal(session.getSession(), null);
    assert.equal(storage.size,0);
  } finally { globalThis.fetch=previous.fetch; globalThis.sessionStorage=previous.sessionStorage; }
});
