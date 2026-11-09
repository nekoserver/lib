"""Key-gated conversation HTML/assets; public entry contains only key exchange UI."""
import secrets
from pathlib import Path
from aiohttp import web
from chat_access import authorize_request

COOKIE = '__Host-conversation-observer'
LANDING = '/lib/conversation-embed.html'
ROOT = Path(__file__).resolve().parents[1]


def register_site(app, secret, origins, root=ROOT, frame_origins=None, valid_asset_ticket=None):
    """Attach the login entry and protected assets without altering their bytes."""
    frame_origins = origins if frame_origins is None else frame_origins
    def authorized(request):
        return authorize_request(
            secret, method=request.method, path=request.raw_path,
            headers=request.headers, cookies=request.cookies,
            origin='https://' + request.host, allowed_origins=origins,
        )

    async def entry(request):
        if authorized(request):
            return web.Response(status=302, headers={'Location': LANDING, 'Cache-Control': 'private, no-store'})
        nonce = secrets.token_hex(16)
        page = '''<!doctype html><html lang="ja" data-auth-gate="conversation"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>認証</title><body>
<form id="login"><label>認証キー <input id="key" type="password" autocomplete="off" required></label><button>認証して開く</button></form><p id="status" role="status"></p>
<script nonce="NONCE">
const form = document.getElementById('login');
const STORAGE = 'conversation-observer-session-v1';
function openWithTicket(data) {
 if (!data || typeof data.token !== 'string' || !Number.isFinite(data.expires_in) || !/^[A-Za-z0-9_-]{20,80}$/.test(data.asset_ticket || '')) throw new Error('invalid_session');
 const expires = Date.now() + data.expires_in * 1000;
 try { sessionStorage.setItem(STORAGE, JSON.stringify({token:data.token, expires})); }
 catch { throw new Error('session_storage_unavailable'); }
 location.replace('/lib/t/' + data.asset_ticket + '/conversation-embed.html' + location.search);
}
try {
 const cached = JSON.parse(sessionStorage.getItem(STORAGE));
 if (cached && typeof cached.token === 'string' && Number.isFinite(cached.expires) && cached.expires > Date.now()) {
  fetch('/lib/api/chat/session', {headers:{Authorization:'Bearer ' + cached.token}, cache:'no-store'}).then(async response => {
   if (response.ok) openWithTicket(await response.json());
  }).catch(() => {});
 }
} catch {}
form.addEventListener('submit', async event => {
 event.preventDefault();
 const field = document.getElementById('key'), status = document.getElementById('status');
 try {
  const encoder = new TextEncoder(), body = '{"type":"observe"}', path = '/lib/api/chat/session';
  const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2,'0')).join('');
  const key = await crypto.subtle.importKey('raw', encoder.encode(field.value.trim()), {name:'HMAC',hash:'SHA-256'}, false, ['sign']);
  field.value = '';
  const timestamp = String(Math.floor(Date.now()/1000));
  const digest = hex(await crypto.subtle.digest('SHA-256', encoder.encode(body)));
  const signature = hex(await crypto.subtle.sign('HMAC', key, encoder.encode('POST\\n'+path+'\\n'+timestamp+'\\n'+digest)));
  const response = await fetch(path, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-Timestamp':timestamp,'X-Signature':signature}, body});
  if (!response.ok) throw new Error('denied');
  const data = await response.json();
  const cookie = await fetch('/lib/api/chat/session', {cache:'no-store'}).catch(() => null);
  if (cookie && cookie.ok) {
   try { sessionStorage.setItem(STORAGE, JSON.stringify({token:data.token, expires:Date.now()+data.expires_in*1000})); } catch {}
   location.replace('/lib/conversation-embed.html' + location.search);
  } else openWithTicket(data);
 } catch (error) { status.textContent = error?.message === 'session_storage_unavailable' ? 'このブラウザーではセッションを保存できませんでした。サイトデータの使用を許可して再度お試しください。' : '認証できませんでした。キーを確認してください。'; }
});
</script></body></html>'''.replace('NONCE', nonce)
        return web.Response(text=page, content_type='text/html', headers={
            'Cache-Control': 'private, no-store', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; script-src 'nonce-" + nonce + "'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self' " + ' '.join(sorted(frame_origins)),
            'X-Content-Type-Options': 'nosniff',
        })

    async def serve_asset(request, path):
        if path != LANDING and not path.startswith('/lib/chat/'):
            raise web.HTTPForbidden()
        candidate = (root / path.removeprefix('/lib/')).resolve()
        allowed_root = (root / 'chat').resolve()
        if candidate != (root / 'conversation-embed.html').resolve() and not candidate.is_relative_to(allowed_root):
            raise web.HTTPForbidden()
        if not candidate.is_file() or candidate.name.startswith('.'):
            raise web.HTTPNotFound()
        response = web.FileResponse(candidate, headers={'Cache-Control': 'private, no-store', 'Vary': 'Cookie', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})
        if candidate.suffix == '.mjs':
            response.content_type = 'text/javascript'
        return response

    async def ticket_asset(request):
        path = '/lib/' + request.match_info['path']
        if not valid_asset_ticket or not valid_asset_ticket(request.match_info['ticket']):
            if path == LANDING:
                raise web.HTTPFound(LANDING, headers={'Cache-Control': 'no-store'})
            return web.json_response({'error': 'asset_ticket_expired'}, status=401, headers={'Cache-Control': 'no-store'})
        return await serve_asset(request, path)

    async def asset(request):
        if not authorized(request):
            # A directly embedded HTML page can authenticate inside its iframe.
            # Raw asset/API clients still receive a non-cacheable 401.
            if request.path == LANDING and 'text/html' in request.headers.get('Accept', ''):
                return await entry(request)
            return web.json_response({'error': 'authentication_required'}, status=401, headers={'Cache-Control': 'private, no-store', 'Vary': 'Cookie'})
        return await serve_asset(request, request.path)

    app.router.add_get('/', entry)
    app.router.add_get('/lib/t/{ticket}/{path:.*}', ticket_asset)
    app.router.add_get('/lib/{path:.*}', asset)
