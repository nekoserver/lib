const streamError = (message, code) => Object.assign(new Error(message), { code });
export class ChatSocket {
  constructor(url, { WebSocketClass = globalThis.WebSocket, crypto = globalThis.crypto } = {}) {
    this.url = url;
    this.WebSocketClass = WebSocketClass;
    this.crypto = crypto;
    this.socket = null;
  }

  cancel() { this.socket?.close(1000, 'stop_watching'); }

  watch(secret, request, onUpdate, sessionToken = null) {
    if (this.socket) return Promise.reject(new Error('すでに接続中です。'));
    return new Promise((resolve, reject) => {
      const ws = new this.WebSocketClass(this.url);
      this.socket = ws;
      let phase = 'challenge', settled = false;
      const finish = error => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (this.socket === ws) this.socket = null;
        secret = '';
        ws.close();
        error ? reject(error) : resolve();
      };
      const timer = request.type === 'observe' ? null : setTimeout(() => finish(new Error('接続がタイムアウトしました。')), 325000);
      ws.onmessage = async event => {
        try {
          const data = JSON.parse(event.data);
          if (phase === 'challenge' && data.type === 'challenge' && /^[0-9a-f]{64}$/.test(data.nonce)) {
            if (sessionToken && request.type === 'observe') {
              phase = 'authenticating';
              ws.send(JSON.stringify({ type: 'session_auth', token: sessionToken }));
              return;
            }
            if (request.type === 'demo') {
              phase = 'authenticating';
              ws.send(JSON.stringify({ type: 'demo_auth' }));
              return;
            }
            phase = 'signing';
            const enc = new TextEncoder();
            const key = await this.crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
            secret = '';
            const signature = await this.crypto.subtle.sign('HMAC', key, enc.encode(`WS\n/lib/api/chat/ws\n${data.nonce}`));
            if (settled) return;
            phase = 'authenticating';
            ws.send(JSON.stringify({ type: 'auth', signature: [...new Uint8Array(signature)].map(b => b.toString(16).padStart(2, '0')).join('') }));
          } else if (phase === 'authenticating' && data.type === 'authenticated') {
            phase = 'watching';
            ws.send(JSON.stringify(request));
          } else if (phase === 'watching' && ['job', 'delta', 'heartbeat', 'info', 'conversation'].includes(data.type)) {
            onUpdate(data);
            if (data.type === 'job' && !['pending', 'running'].includes(data.ask_status)) finish();
          } else if (data.type === 'error') {
            const messages = {
              worker_unavailable: 'AI実行サーバーに接続できません。',
              connection_timeout: '接続がタイムアウトしました。結果に再接続してください。',
              invalid_request: '送信内容またはサーバーの応答が不正です。',
            };
            finish(streamError(messages[data.error] || 'サーバーでエラーが発生しました。', data.error));
          } else {
            finish(new Error('サーバーの応答が不正です。'));
          }
        } catch (error) { finish(error); }
      };
      ws.onerror = () => finish(streamError('WebSocketに接続できません。サーバーと公開経路を確認してください。', 'websocket_unavailable'));
      ws.onclose = event => { if (event.code === 1008) onUpdate({ type: 'session_expired' }); finish(streamError(event.code === 1008 ? '認証に失敗しました。HMACキーを確認してください。' : event.reason === 'stop_watching' ? '受信を停止しました。' : '接続が切れました。再接続して確認してください。', event.code === 1008 ? 'auth_rejected' : event.reason === 'stop_watching' ? 'stopped' : 'disconnected')); };
    });
  }
}
