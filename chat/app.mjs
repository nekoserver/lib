import { ChatSocket } from './socket.mjs';
import { showMarkdown } from './markdown.mjs';

const $ = id => document.getElementById(id);
const url = new URL('/lib/api/chat/ws', location.href);
url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const client = new ChatSocket(url.href);
let askId = null;
let busy = false;

function setBusy(value) {
  busy = value;
  $('send').disabled = value;
  $('resume').disabled = value || !askId;
  $('stop').disabled = !value;
  $('engine').disabled = value;
}

async function watch(request) {
  if (busy) return;
  const secret = $('secret').value;
  if (!secret) { $('status').textContent = 'HMACキーを入力してください。'; return; }
  if (!globalThis.isSecureContext || !globalThis.crypto?.subtle) {
    $('status').textContent = 'HTTPSでページを開いてください。'; return;
  }
  $('secret').value = '';
  if (request.type === 'submit') { askId = null; $('job').textContent = ''; $('answer').textContent = ''; $('metadata').textContent = ''; }
  setBusy(true);
  $('status').textContent = '接続・認証中…';
  try {
    await client.watch(secret, request, data => {
      if (data.ask_id) { askId = data.ask_id; $('job').textContent = askId; }
      $('status').textContent = ({ pending: '実行待ち', running: '回答を生成中…', done: '完了', failed: '実行失敗' })[data.ask_status] || '状態不明';
      if (data.reply !== undefined) showMarkdown($('answer'), data.reply);
      if (data.ask_error) $('status').textContent = `実行失敗: ${data.ask_error}`;
      $('metadata').textContent = [data.llm_model, data.llm_effort && `effort: ${data.llm_effort}`].filter(Boolean).join(' / ');
    });
  } catch (error) { $('status').textContent = error.message; }
  finally { setBusy(false); }
}

$('form').addEventListener('submit', event => {
  event.preventDefault();
  const prompt = $('prompt').value;
  if (!prompt.trim()) { $('status').textContent = 'メッセージを入力してください。'; return; }
  if (new TextEncoder().encode(prompt).length > 16384) { $('status').textContent = 'メッセージは16 KiB以内にしてください。'; return; }
  watch({ type: 'submit', engine: $('engine').value, prompt });
});
$('resume').addEventListener('click', () => { if (askId) watch({ type: 'resume', ask_id: askId }); });
$('stop').addEventListener('click', () => client.cancel());
window.addEventListener('pagehide', () => client.cancel());
setBusy(false);
