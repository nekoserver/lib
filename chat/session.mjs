const STORAGE = 'conversation-observer-session-v1';
let current = null;
const hex = value => [...new Uint8Array(value)].map(b => b.toString(16).padStart(2, '0')).join('');
export function getSession() {
  if (!current) { try { current = JSON.parse(sessionStorage.getItem(STORAGE)); } catch {} }
  if (!current || current.expires <= Date.now()) { clearSession(); return null; }
  return current.token;
}
export function clearSession() {
  current = null;
  try { sessionStorage.removeItem(STORAGE); } catch {}
}
export async function startSession(secret) {
  const path = '/lib/api/chat/session', body = JSON.stringify({ type: 'observe' });
  const enc = new TextEncoder(), timestamp = String(Math.floor(Date.now() / 1000));
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  secret = '';
  const hash = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
  const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(`POST\n${path}\n${timestamp}\n${hash}`)));
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Timestamp': timestamp, 'X-Signature': signature }, body, cache: 'no-store' });
  if (!response.ok) throw new Error(response.status === 401 ? 'HMACキーを確認してください。' : '認証できませんでした。');
  const data = await response.json();
  if (typeof data.token !== 'string' || typeof data.expires_in !== 'number') throw new Error('認証応答が不正です。');
  current = { token: data.token, expires: Date.now() + data.expires_in * 1000 };
  try { sessionStorage.setItem(STORAGE, JSON.stringify(current)); } catch {}
  return current.token;
}
