import { applyEmbedTheme } from './theme-35abe6ad011b.mjs';
import { getSession, startSession, restoreSession, clearSession, sessionForKey } from './session-580027ffdf0c.mjs';
import { ChatSocket } from './socket-615279be1675.mjs';
import { showMarkdown } from './markdown-1eb47137e336.mjs';
import { ObserveReconnect, reconnectStatus } from './reconnect-8a7b7765a559.mjs';
import { HttpStream } from './http-stream-060b37ef915d.mjs';

const $ = id => document.getElementById(id);
const hex = value => [...new Uint8Array(value)].map(byte => byte.toString(16).padStart(2, '0')).join('');
const embedded = document.documentElement.dataset.embed === 'conversation';
const CONSOLE_TTL_OPTIONS = new Set([900, 3600, 28800, 86400, 604800]);
const CONSOLE_STORAGE = 'conversation-console-session-v1';
let consoleTtlSeconds = 3600;
const parentOrigins = new Set([location.origin, 'https://1.cfw1.nekomaneki.work', 'https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev', 'https://dynamicneko.nekoflare.workers.dev']);
let parentOrigin = null;
if (embedded) {
  const parameters = new URLSearchParams(location.search);
  if (['sse', 'websocket', 'ndjson', 'jsonseq'].includes(parameters.get('protocol'))) $('protocol').value = parameters.get('protocol');
  document.documentElement.dataset.theme = parameters.get('theme') === 'light' ? 'light' : 'dark';
  window.addEventListener('message', event => {
    if (event.source !== window.parent) return;
    // Cosmetic updates have no authentication or stream-control authority.
    if (applyEmbedTheme(document.documentElement, event.data)) {
      window.parent.postMessage({ type: 'conversation-theme-applied', themeId: event.data.themeId }, event.origin);
      return;
    }
    if (!parentOrigins.has(event.origin)) return;
    parentOrigin = event.origin;
    if (event.data?.type === 'conversation-controls') {
      document.documentElement.dataset.parentControls = 'true';
      if (CONSOLE_TTL_OPTIONS.has(event.data.consoleTtlSeconds)) consoleTtlSeconds = event.data.consoleTtlSeconds;
      updateConsoleSection(); notifyParent({ type: 'conversation-state', busy });
    }
    if (event.data?.type === 'conversation-start') watch({ type: 'observe' });
    if (event.data?.type === 'conversation-stop') stopWatching();
    if (event.data?.type === 'conversation-theme' && ['light', 'dark'].includes(event.data.theme)) document.documentElement.dataset.theme = event.data.theme;
  });
  window.parent.postMessage({ type: 'conversation-theme-ready' }, '*');
}
const url = new URL('/lib/api/chat/ws', location.href);
url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
let client = null;
let askId = null;
let busy = false;
let consoleAuthorized = false;
let consoleBusy = false;
let consoleExpiresAt = 0;
let consoleToken = null;
const reconnect = new ObserveReconnect(() => watch({ type: 'observe' }));
function stopWatching() { reconnect.stop(); client?.cancel(); }
let answer = '';
const messageNodes = new Map();
let focusLatestOnNextSnapshot = true;

function renderConversation(data) {
  const container = $('conversation');
  const scroller = embedded ? container.closest('section') : container;
  const focusLatest = focusLatestOnNextSnapshot;
  const follow = focusLatest || scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  const fragment = document.createDocumentFragment(), retained = new Set();
  for (const message of data.messages) {
    retained.add(message.id);
    let record = messageNodes.get(message.id);
    if (!record) {
      const element = document.createElement('article');
      element.className = `message ${message.role === 'user' ? 'user' : 'assistant'}`;
      element.tabIndex = -1;
      const label = document.createElement('p'); label.className = 'message-label';
      const content = document.createElement('div'); content.className = 'markdown';
      element.append(label, content);
      record = { element, label, content, text: null };
      messageNodes.set(message.id, record);
    }
    record.label.textContent = message.role === 'user' ? 'あなた' : message.phase === 'commentary' ? 'AI · 作業の更新' : 'AI';
    if (record.text !== message.text) {
      if (message.role === 'user') record.content.textContent = message.text;
      else showMarkdown(record.content, message.text);
      record.text = message.text;
    }
    fragment.append(record.element);
  }
  for (const id of messageNodes.keys()) if (!retained.has(id)) messageNodes.delete(id);
  container.replaceChildren(fragment);
  container.hidden = false;
  $('answer').hidden = true;
  if (data.messages.length) {
    focusLatestOnNextSnapshot = false;
    requestAnimationFrame(() => {
      if (follow) scroller.scrollTop = scroller.scrollHeight;
      if (focusLatest) container.lastElementChild?.focus({ preventScroll: true });
    });
  }
  $('status').textContent = data.status === 'notLoaded' ? '監視対象の会話は終了しています。サーバーの監視先設定を確認してください。' : data.status === 'active' ? 'この会話を表示中 · AIが作業中' : 'この会話を表示中 · 次の更新を待っています';
  const activities = { commandExecution: 'コマンド', webSearch: '検索', fileChange: 'ファイル変更', mcpToolCall: 'ツール', dynamicToolCall: 'ツール' };
  $('activity').textContent = data.activity.map(item => activities[item.kind] || 'ツール').join(' · ');
}

function updateSource() {
  if (embedded) $('source').value = 'conversation';
  const observing = $('source').value === 'conversation';
  $('ai-fields').hidden = observing;
  $('send').textContent = observing ? '表示を開始' : '別のAI実行に送信';
}
$('source').addEventListener('change', updateSource);
updateSource();
const descriptions = {
  sse: 'SSE：サーバーからイベントを配信。認証ヘッダーを送れるfetchで受信します。',
  websocket: 'WebSocket：双方向のメッセージ通信。ここでは送信と状態・回答の受信に使います。',
  ndjson: 'NDJSON：HTTPレスポンスを読みながら、1行ずつJSONを受信します。',
  jsonseq: 'JSON Text Sequence：RS文字で区切ったJSONレコードを受信します。',
};
function describe() { $('protocol-hint').textContent = descriptions[$('protocol').value]; }
describe();
$('protocol').addEventListener('change', describe);

function notifyParent(data) { if (embedded && parentOrigin) window.parent.postMessage(data, parentOrigin); }

function setBusy(value) {
  busy = value;
  $('send').disabled = value;
  $('resume').disabled = value || !askId;
  $('stop').disabled = !value && reconnect.timer === null;
  $('engine').disabled = value;
  $('protocol').disabled = value;
  $('demo').disabled = value;
  $('source').disabled = value;
  notifyParent({ type: 'conversation-state', busy: value });
}

async function watch(request) {
  if (busy) return;
  let secret = $('secret').value.trim();
  let sessionToken = request.type === 'observe' ? await sessionForKey(secret) : null;
  if (busy) return;
  if (!secret && !sessionToken && request.type !== 'demo') { $('status').textContent = 'HMACキーを入力してください。'; return; }
  if (!globalThis.isSecureContext || !globalThis.crypto?.subtle) {
    $('status').textContent = 'HTTPSでページを開いてください。'; return;
  }
  if (request.type === 'observe') reconnect.begin(); else reconnect.stop();
  $('secret').value = '';
  if (request.type !== 'resume') { askId = null; answer = ''; $('job').textContent = ''; $('answer').textContent = ''; $('metadata').textContent = ''; }
  if (request.type === 'observe') focusLatestOnNextSnapshot = true;
  $('conversation').hidden = true;
  $('answer').hidden = false;
  $('activity').textContent = '';
  const protocol = $('protocol').value;
  client = protocol === 'websocket' ? new ChatSocket(url.href) : new HttpStream(protocol);
  $('stats').textContent = '受信を待っています…';
  const started = performance.now();
  let count = 0, first = null, previous = started;
  setBusy(true);
  $('status').textContent = '接続・認証中…';
  try {
    if (request.type === 'observe') {
      if (!sessionToken) sessionToken = await startSession(secret);
      secret = '';
      hideKeyInput(true);
      restoreConsoleAuthorization();
    }
    await client.watch(secret, request, data => {
      if (data.type === 'session_expired') { clearSession(); hideKeyInput(false); return; }
      const now = performance.now();
      if (first === null) first = now - started;
      count++;
      $('stats').textContent = `受信 ${count} 件 / 最初のイベント ${Math.round(first)} ms / 直近の間隔 ${Math.round(now - previous)} ms / 経過 ${((now - started) / 1000).toFixed(1)} 秒`;
      previous = now;
      if (data.type === 'info') {
        $('delivery').textContent = data.source === 'conversation' ? 'このコンソールの会話を表示します。下の入力欄から、この会話へ直接メッセージを送れます。' : data.source === 'demo' ? '比較デモ：固定文章を分割配信。AIは実行しません。' : '別のAI実行：状態は随時配信、回答は生成完了時に届きます。文字単位の生成配信ではありません。';
        return;
      }
      if (data.type === 'conversation') { reconnect.reset(); renderConversation(data); return; }
      if (data.type === 'heartbeat') return;
      if (data.type === 'delta') { answer += data.text; showMarkdown($('answer'), answer); return; }
      if (data.ask_id) { askId = data.ask_id; $('job').textContent = askId; }
      $('status').textContent = ({ pending: '実行待ち', running: '回答を生成中…', done: '完了', failed: '実行失敗' })[data.ask_status] || '状態不明';
      if (data.reply !== undefined) { answer = data.reply; showMarkdown($('answer'), answer); }
      if (data.ask_error) $('status').textContent = `実行失敗: ${data.ask_error}`;
      $('metadata').textContent = [data.llm_model, data.llm_effort && `effort: ${data.llm_effort}`].filter(Boolean).join(' / ');
    }, sessionToken);
  } catch (error) {
    $('status').textContent = error.message; if (!getSession()) hideKeyInput(false);
    if (request.type === 'observe') {
      if (protocol === 'websocket' && error.code === 'websocket_unavailable') {
        $('protocol').value = 'sse'; describe();
        notifyParent({ type: 'conversation-transport', protocol: 'sse' });
      }
      const delay = reconnect.schedule(error, Boolean(getSession()));
      if (delay !== null) $('status').textContent = reconnectStatus(error, delay);
    }
  }
  finally { setBusy(false); }
}

$('form').addEventListener('submit', event => {
  event.preventDefault();
  if (embedded || $('source').value === 'conversation') { watch({ type: 'observe' }); return; }
  const prompt = $('prompt').value;
  if (!prompt.trim()) { $('status').textContent = 'メッセージを入力してください。'; return; }
  if (new TextEncoder().encode(prompt).length > 16384) { $('status').textContent = 'メッセージは16 KiB以内にしてください。'; return; }
  watch({ type: 'submit', engine: $('engine').value, prompt });
});
$('resume').addEventListener('click', () => { if (askId) watch({ type: 'resume', ask_id: askId }); });
$('demo').addEventListener('click', () => watch({ type: 'demo' }));
$('stop').addEventListener('click', () => stopWatching());
window.addEventListener('pagehide', () => stopWatching());
setBusy(false);

function hideKeyInput(hidden) {
  if (embedded) document.documentElement.dataset.authenticated = String(hidden);
  for (const node of document.querySelectorAll('label[for="secret"], #secret, #key-hint')) node.hidden = hidden;
  updateConsoleSection();
}
function updateConsoleSection() {
  if (!$('console-section')) return;
  const parentReady = embedded && document.documentElement.dataset.parentControls === 'true';
  const observerReady = document.documentElement.dataset.authenticated === 'true';
  let secondsLeft = consoleAuthorized && consoleExpiresAt ? Math.max(0, Math.ceil((consoleExpiresAt - Date.now()) / 1000)) : 0;
  if (consoleAuthorized && secondsLeft === 0) {
    consoleAuthorized = false;
    consoleExpiresAt = 0;
    void revokeConsoleCapability();
    $('console-status').textContent = '送信許可の期限が切れました。HMACキーを再入力してください。';
  }
  $('console-section').hidden = !(parentReady && observerReady);
  $('console-prompt').disabled = consoleBusy;
  $('console-send').disabled = consoleBusy;
  $('console-key-entry').hidden = consoleAuthorized;
  $('console-countdown').hidden = !consoleAuthorized;
  if (consoleAuthorized) $('console-countdown').textContent = `残り ${formatRemaining(secondsLeft)}`;
  $('console-revoke').hidden = !consoleAuthorized;
}
function formatRemaining(seconds) {
  const days = Math.floor(seconds / 86400), hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60), secs = seconds % 60;
  return days ? `${days}日 ${hours}時間` : hours ? `${hours}時間 ${minutes}分` : minutes ? `${minutes}分 ${secs}秒` : `${secs}秒`;
}
function cachedConsoleSession() {
  try {
    const value = JSON.parse(sessionStorage.getItem(CONSOLE_STORAGE));
    if (typeof value?.token === 'string' && Number.isFinite(value.expires) && value.expires > Date.now()) return value;
  } catch {}
  return null;
}
function storeConsoleSession(token, expiresAt) {
  consoleToken = token;
  try { sessionStorage.setItem(CONSOLE_STORAGE, JSON.stringify({ token, expires: expiresAt })); } catch {}
}
function dropConsoleToken() {
  consoleToken = null;
  try { sessionStorage.removeItem(CONSOLE_STORAGE); } catch {}
}
async function revokeConsoleCapability() {
  const cached = consoleToken || cachedConsoleSession()?.token;
  await fetch('/lib/api/chat/console-session', {
    method: 'DELETE', credentials: 'same-origin', cache: 'no-store',
    headers: cached ? { Authorization: `Bearer ${cached}` } : {}
  }).catch(() => {});
  dropConsoleToken();
  consoleAuthorized = false;
  consoleExpiresAt = 0;
}
async function signedJsonPost(path, value, secret) {
  const body = JSON.stringify(value), timestamp = String(Math.floor(Date.now() / 1000));
  const enc = new TextEncoder(), key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const hash = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
  const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(`POST\n${path}\n${timestamp}\n${hash}`)));
  return fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Timestamp': timestamp, 'X-Signature': signature }, body, cache: 'no-store' });
}
async function restoreConsoleAuthorization() {
  try {
    const cached = cachedConsoleSession();
    const response = await fetch('/lib/api/chat/console-session', {
      credentials: 'same-origin', cache: 'no-store',
      ...(cached ? { headers: { Authorization: `Bearer ${cached.token}` } } : {})
    });
    if (response.ok) {
      const data = await response.json();
      consoleAuthorized = data.enabled === true && Number.isFinite(data.expires_in) && data.expires_in > 0;
      consoleExpiresAt = consoleAuthorized ? Date.now() + data.expires_in * 1000 : 0;
      if (consoleAuthorized && typeof data.token === 'string') storeConsoleSession(data.token, consoleExpiresAt);
      else dropConsoleToken();
    }
  } catch {}
  updateConsoleSection();
}
$('console-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (consoleBusy) return;
  const prompt = $('console-prompt').value;
  if (!prompt.trim()) { $('console-status').textContent = 'メッセージを入力してください。'; return; }
  if (new TextEncoder().encode(prompt).length > 16_384) { $('console-status').textContent = 'メッセージは16 KiB以内にしてください。'; return; }
  consoleBusy = true; updateConsoleSection(); $('console-status').textContent = consoleAuthorized ? 'コンソールへ送信中…' : '送信を許可しています…';
  try {
    if (!consoleAuthorized) {
      const secret = $('console-key').value;
      if (!secret.trim()) throw new Error('既存のHMACキーを入力してください。');
      const auth = await signedJsonPost('/lib/api/chat/console-session', { type: 'console', ttl_seconds: consoleTtlSeconds }, secret.trim());
      $('console-key').value = '';
      if (!auth.ok) throw new Error(auth.status === 401 ? 'HMACキーを確認してください。' : `認証に失敗しました（HTTP ${auth.status}）。`);
      const data = await auth.json();
      if (typeof data.token !== 'string' || !Number.isFinite(data.expires_in) || data.expires_in <= 0) throw new Error('送信許可の応答が不正です。');
      consoleAuthorized = true;
      consoleExpiresAt = Date.now() + data.expires_in * 1000;
      storeConsoleSession(data.token, consoleExpiresAt);
    }
    const response = await fetch('/lib/api/chat/console', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${consoleToken}` }, body: JSON.stringify({ prompt }), cache: 'no-store' });
    if (response.status === 401) {
      await revokeConsoleCapability();
      throw new Error('送信許可を確認できませんでした。キーを再入力して許可し直してください。');
    }
    if (!response.ok) throw new Error(response.status === 503 ? 'Codexコンソールに接続できません。' : `送信に失敗しました（HTTP ${response.status}）。`);
    $('console-prompt').value = '';
    $('console-status').textContent = '送信しました。この会話に応答が届きます。';
  } catch (error) {
    $('console-status').textContent = error instanceof Error ? error.message : '送信に失敗しました。';
  } finally { consoleBusy = false; updateConsoleSection(); }
});
$('console-revoke').addEventListener('click', async () => {
  await revokeConsoleCapability();
  $('console-status').textContent = '送信許可を解除しました。'; updateConsoleSection();
});
updateConsoleSection();
setInterval(updateConsoleSection, 1000);
if (embedded) restoreSession().then(token => { if (token) { hideKeyInput(true); watch({ type: 'observe' }); restoreConsoleAuthorization(); } });
