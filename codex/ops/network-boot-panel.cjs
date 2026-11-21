const { chromium } = require('/root/cloudflare-workers-github-oauth-1/node_modules/playwright');
const key = process.env.ORIGIN_HMAC_SECRET || process.env.HMAC_SECRET;
const origin = 'https://mygw.nekomaneki.work';
async function main() {
  const env = { ...process.env };
  delete env.ORIGIN_HMAC_SECRET;
  delete env.HMAC_SECRET;
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'], env
  });
  let phase = 'パネルを開く';
  try {
    const page = await browser.newPage();
    const iframeUrl = origin + '/lib/conversation-embed.html?via=aichat-panel';
    await page.route(origin + '/__network_test_parent', route => route.fulfill({
      contentType: 'text/html',
      body: `<iframe id="panel" src="${iframeUrl}" width="1000" height="850"></iframe>
      <script>addEventListener('message', e => {
        const child = document.querySelector('iframe').contentWindow;
        if (e.source === child && e.origin === location.origin && e.data?.type === 'conversation-theme-ready') {
          child.postMessage({type:'conversation-controls', observationControls:'parent'}, e.origin);
        }
      });</script>`
    }));
    await page.goto(origin + '/__network_test_parent', { timeout: 20000 });
    const panel = page.frameLocator('#panel');
    phase = '既存HMACで閲覧を許可';
    await panel.locator('#login #key').fill(key, { timeout: 10000 });
    await panel.locator('#login button').click();
    phase = '投稿フォームを開く';
    await panel.locator('#console-prompt').waitFor({ state: 'visible', timeout: 20000 });
    const marker = 'STREAM_POST_OK_' + Date.now();
    await panel.locator('#console-prompt').fill(marker + ' とだけ返答してください');
    await panel.locator('#console-key').fill(key);
    phase = 'パネルから一度だけ送信';
    const posting = page.waitForResponse(r => new URL(r.url()).pathname === '/lib/api/chat/console'
      && r.request().method() === 'POST', { timeout: 28000 });
    await panel.locator('#console-send').click();
    const response = await posting;
    const body = await response.json().catch(() => ({}));
    console.log('ブラウザ投稿 HTTP=' + response.status() + ' accepted=' + (body.accepted === true));
    if (!body.accepted) throw new Error('post rejected');
    phase = '会話欄に返信が届くまで待機';
    await page.frame({url: /conversation-embed/}).waitForFunction(marker => {
      return [...document.querySelectorAll('#conversation .message.assistant')]
        .some(message => [...message.querySelectorAll('p')].some(paragraph => paragraph.textContent.trim() === marker));
    }, marker, { timeout: 50000 });
    console.log('ブラウザ会話欄で投稿とマーカー返信を確認');
  } catch {
    console.log('ブラウザ検査失敗箇所 ' + phase);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}
main().catch(() => { console.log('ブラウザ起動失敗'); process.exitCode = 1; });
