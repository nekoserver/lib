const STORAGE = 'conversation-observer-session-v1';
let current = null;
let restoring = null;
const hex = value => [...new Uint8Array(value)].map(b => b.toString(16).padStart(2, '0')).join('');
export function getSession() {
  if (!current) { try { current = JSON.parse(sessionStorage.getItem(STORAGE)); } catch {} }
  if (!current) return null;
  if (typeof current.token !== 'string' || !current.token || !Number.isFinite(current.expires) || current.expires <= Date.now()) { clearLocalSession(); return null; }
  return current.token;
}
function clearLocalSession() {
  current = null;
  try { sessionStorage.removeItem(STORAGE); } catch {}
}
export function clearSession() {
  clearLocalSession();
  fetch('/lib/api/chat/session', { method: 'DELETE', credentials: 'same-origin', cache: 'no-store' }).catch(() => {});
}

export async function restoreSession() {
  const cached = getSession();
  if (restoring) return restoring;
  restoring = (async () => {
    try {
      const response = await fetch('/lib/api/chat/session', { credentials: 'same-origin', cache: 'no-store', ...(cached ? { headers: { Authorization: 'Bearer ' + cached } } : {}) });
      if (!response.ok) {
        if (response.status === 401) { clearLocalSession(); return null; }
        return cached;
      }
      const data = await response.json();
      if (typeof data.token !== 'string' || !Number.isFinite(data.expires_in) || data.expires_in <= 0) return null;
      current = { token: data.token, expires: Date.now() + data.expires_in * 1000 };
      try { sessionStorage.setItem(STORAGE, JSON.stringify(current)); } catch {}
      return current.token;
    } catch { return cached; }
  })();
  try { return await restoring; } finally { restoring = null; }
}
export async function startSession(secret) {
  if (typeof secret !== 'string' || !secret.length) throw new Error('HMACキーを入力してください。');
  const path = '/lib/api/chat/session', body = JSON.stringify({ type: 'observe' });
  const enc = new TextEncoder(), timestamp = String(Math.floor(Date.now() / 1000));
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  secret = '';
  const hash = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
  const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(`POST\n${path}\n${timestamp}\n${hash}`)));
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Timestamp': timestamp, 'X-Signature': signature }, body, cache: 'no-store' });
  if (!response.ok) throw new Error(response.status === 401 ? 'HMACキーを確認してください。' : '認証できませんでした。');
  const data = await response.json();
  if (typeof data.token !== 'string' || typeof data.expires_in !== 'number') throw new Error('認証応答が不正です。');
  current = { token: data.token, expires: Date.now() + data.expires_in * 1000 };
  try { sessionStorage.setItem(STORAGE, JSON.stringify(current)); } catch {}
  return current.token;
}
