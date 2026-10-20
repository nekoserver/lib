import { applyEmbedTheme } from './theme.mjs';
import { getSession, startSession, restoreSession, clearSession, sessionForKey } from './session.mjs?v=cookie7d';
import { ChatSocket } from './socket.mjs?v=controls3';
import { showMarkdown } from './markdown.mjs';
import { ObserveReconnect, reconnectStatus } from './reconnect.mjs';
import { HttpStream } from './http-stream.mjs?v=controls3';

const $ = id => document.getElementById(id);
const embedded = document.documentElement.dataset.embed === 'conversation';
const parentOrigins = new Set([location.origin, 'https://1.cfw1.nekomaneki.work', 'https://cloudflare-workers-github-oauth-1.nekoflare.workers.dev']);
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
    if (event.data?.type === 'conversation-controls') { document.documentElement.dataset.parentControls = 'true'; notifyParent({ type: 'conversation-state', busy }); }
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
  $('events').textContent = '';
  $('stats').textContent = '受信を待っています…';
  const started = performance.now();
  let count = 0, first = null, previous = started;
  const log = [];
  setBusy(true);
  $('status').textContent = '接続・認証中…';
  try {
    if (request.type === 'observe') {
      if (!sessionToken) sessionToken = await startSession(secret);
      secret = '';
      hideKeyInput(true);
    }
    await client.watch(secret, request, data => {
      if (data.type === 'session_expired') { clearSession(); hideKeyInput(false); return; }
      const now = performance.now();
      if (first === null) first = now - started;
      count++;
      $('stats').textContent = `受信 ${count} 件 / 最初のイベント ${Math.round(first)} ms / 直近の間隔 ${Math.round(now - previous)} ms / 経過 ${((now - started) / 1000).toFixed(1)} 秒`;
      previous = now;
      const preview = { ...data };
      if (preview.messages) preview.messages = `${preview.messages.length}件の会話メッセージ（本文は上に表示）`;
      if (preview.reply) preview.reply = preview.reply.slice(0, 120) + (preview.reply.length > 120 ? '…' : '');
      log.push(`${((now - started) / 1000).toFixed(2)}s ${JSON.stringify(preview)}`);
      if (log.length > 60) log.shift();
      $('events').textContent = log.join('\n');
      if (data.type === 'info') {
        $('delivery').textContent = data.source === 'conversation' ? 'この会話の閲覧専用表示です。履歴と状態を約1秒間隔で確認します。Web画面からのメッセージ送信は行いません。' : data.source === 'demo' ? '比較デモ：固定文章を分割配信。AIは実行しません。' : '別のAI実行：状態は随時配信、回答は生成完了時に届きます。文字単位の生成配信ではありません。';
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
}
if (embedded) restoreSession().then(token => { if (token) { hideKeyInput(true); watch({ type: 'observe' }); } });
