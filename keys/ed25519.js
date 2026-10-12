'use strict';
const $ = id => document.getElementById(id);
const endpoint = '/lib/keys/register.rb';
let material = null;
const bytes = value => new Uint8Array(value);
const b64 = value => btoa(String.fromCharCode(...value));
const concat = (...arrays) => { const out = new Uint8Array(arrays.reduce((n, a) => n + a.length, 0)); let offset = 0; for (const a of arrays) { out.set(a, offset); offset += a.length; } return out; };
const sshString = value => { const length = new Uint8Array(4); new DataView(length.buffer).setUint32(0, value.length); return concat(length, value); };
const pem = (label, value) => `-----BEGIN ${label}-----\n${b64(bytes(value)).match(/.{1,64}/g).join('\n')}\n-----END ${label}-----\n`;
const hex = value => [...bytes(value)].map(b => b.toString(16).padStart(2, '0')).join('');
function clear() { material = null; $('private').value = ''; $('public').value = ''; $('secret').value = ''; $('fingerprint').textContent = ''; $('result').hidden = true; $('registration').hidden = true; $('clear').disabled = true; $('register-status').textContent = ''; }
$('generate').addEventListener('click', async () => {
  clear(); $('generate').disabled = true; $('status').textContent = 'キーペアを生成しています…';
  try {
    if (!globalThis.isSecureContext || !crypto.subtle) throw new Error('HTTPSでページを開いてください。');
    const pair = await crypto.subtle.generateKey({name: 'Ed25519'}, true, ['sign', 'verify']);
    const [privateDer, publicDer, publicRaw] = await Promise.all([crypto.subtle.exportKey('pkcs8', pair.privateKey), crypto.subtle.exportKey('spki', pair.publicKey), crypto.subtle.exportKey('raw', pair.publicKey)]);
    const wire = concat(sshString(new TextEncoder().encode('ssh-ed25519')), sshString(bytes(publicRaw)));
    material = {private: pem('PRIVATE KEY', privateDer), public: `ssh-ed25519 ${b64(wire)} browser-pkcs8\n`, spki: pem('PUBLIC KEY', publicDer)};
    $('private').value = material.private; $('public').value = material.public;
    $('fingerprint').textContent = `SHA256:${b64(bytes(await crypto.subtle.digest('SHA-256', wire))).replace(/=+$/, '')}`;
    $('result').hidden = false; $('registration').hidden = false; $('clear').disabled = false; $('status').textContent = '生成完了。秘密鍵を保存してください。公開鍵はまだ登録されていません。';
  } catch (e) { clear(); $('status').textContent = e.name === 'NotSupportedError' ? 'このブラウザはEd25519に対応していません。対応ブラウザで開いてください。' : `生成できませんでした: ${e.message}`; }
  finally { $('generate').disabled = false; }
});
$('clear').addEventListener('click', () => { clear(); $('status').textContent = '画面から鍵を破棄しました。ダウンロード済みファイルや登録済み公開鍵は保持されます。'; });
for (const button of document.querySelectorAll('[data-download]')) button.addEventListener('click', () => {
  if (!material) return;
  const kind = button.dataset.download, url = URL.createObjectURL(new Blob([material[kind]], {type: 'text/plain'}));
  const link = document.createElement('a'); link.href = url; link.download = {private:'private-key.pem',public:'public-key.pub',spki:'public-key.pem'}[kind]; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
for (const button of document.querySelectorAll('[data-copy]')) button.addEventListener('click', async () => {
  try { if (material) { await navigator.clipboard.writeText(material[button.dataset.copy]); $('status').textContent = 'コピーしました。'; } }
  catch { $('status').textContent = 'コピーできませんでした。テキスト欄から手動でコピーしてください。'; }
});
$('register-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!material) return;
  $('register').disabled = true; $('generate').disabled = true; $('clear').disabled = true; $('register-status').textContent = '登録しています…';
  const secret = $('secret').value; $('secret').value = '';
  try {
    const body = JSON.stringify({public_key: material.public.trim()});
    const enc = new TextEncoder(), ts = String(Math.floor(Date.now() / 1000));
    const key = await crypto.subtle.importKey('raw', enc.encode(secret), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
    const bodyHash = hex(await crypto.subtle.digest('SHA-256', enc.encode(body)));
    const signature = hex(await crypto.subtle.sign('HMAC', key, enc.encode(`POST\n${endpoint}\n${ts}\n${bodyHash}`)));
    const response = await fetch(endpoint, {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json','X-Timestamp':ts,'X-Signature':signature},body});
    const data = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? 'HMAC キーを確認してください。' : data.error || '登録に失敗しました。');
    $('register-status').textContent = `${data.added ? '登録しました' : 'この公開鍵は登録済みです'}。root の authorized_keys に反映済みです。`;
  } catch(e) { $('register-status').textContent = e.message; }
  finally { $('register').disabled = false; $('generate').disabled = false; $('clear').disabled = false; }
});
