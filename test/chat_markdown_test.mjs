import test from 'node:test';
import assert from 'node:assert/strict';
import { renderMarkdown } from '../chat/markdown.mjs';

test('AI answers render headings, lists, code fences, links and tables', () => {
  const html = renderMarkdown('# 見出し\n\n**太字** と `code`\n\n- 項目\n\n```js\nconst x = "<tag>";\n```\n\n[リンク](https://example.com)\n\n| 名前 | 値 |\n| --- | --- |\n| A | 1 |');
  for (const fragment of ['<h1>見出し</h1>', '<strong>太字</strong>', '<code>code</code>', '<ul>', '<pre><code class="language-js">', '&lt;tag&gt;', '<a href="https://example.com" target="_blank" rel="noopener noreferrer">', '<table>']) {
    assert.ok(html.includes(fragment), fragment);
  }
});

test('raw HTML and event handlers stay text', () => {
  const html = renderMarkdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>');
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('unsafe Markdown URLs are not made into links or images', () => {
  for (const url of ['javascript:alert(1)', 'jav&#x61;script:alert(1)', 'vbscript:msgbox(1)', 'data:text/html;base64,PHNjcmlwdD4=', 'data:image/svg+xml;base64,PHN2Zz4=']) {
    const html = renderMarkdown(`[bad](${url})\n\n![bad](${url})`);
    assert.ok(!html.includes('<a '), url);
    assert.ok(!html.includes('<img '), url);
  }
});

test('PR links and detected URLs open outside the embedded stream', () => {
  for (const source of ['[PR #2361](https://github.com/nekoserver/cloudflare-workers-github-oauth-1/pull/2361)', 'https://example.com']) {
    const html = renderMarkdown(source);
    assert.ok(html.includes('target="_blank"'));
    assert.ok(html.includes('rel="noopener noreferrer"'));
  }
});
