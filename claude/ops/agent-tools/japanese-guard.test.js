#!/usr/bin/env node
// japanese-guard.js の確認。node ~/.claude/hooks/japanese-guard.test.js で実行する。
'use strict';
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { isEnglish } = require('./japanese-guard.js');

const cases = [
  ['Writing the tests first, in two files: the API and the screen.', true],
  ['Got it: the cause is the second column, which carries the done badge.', true],
  ['テストを先に書きます。`npx vitest run src/views/museInquiries.test.ts` を実行します。', false],
  ['ブランチ `fix/inquiry-plain-titles-20261108` に入っています。src/views/museInquiries.ts を直しました。', false],
  ['```\nconst a = "long english code block that should be ignored entirely";\n```\n直しました。', false],
  ['OK', false],
  ['https://github.com/nekoserver/cloudflare-workers-github-oauth-1/pull/2547', false],
];
for (const [text, expected] of cases) assert.strictEqual(isEnglish(text), expected, text);

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jg-'));
const tr = path.join(dir, 't.jsonl');
const line = (o) => JSON.stringify(o);
fs.writeFileSync(tr, [
  line({ type: 'user', message: { role: 'user', content: '前の質問' } }),
  line({ type: 'assistant', message: { content: [{ type: 'text', text: 'This old English answer belongs to the previous turn and is ignored.' }] } }),
  line({ type: 'user', message: { role: 'user', content: [{ type: 'text', text: '新しい質問' }] } }),
  line({ type: 'assistant', message: { content: [{ type: 'text', text: '調べます。' }, { type: 'tool_use', name: 'Bash', input: {} }] } }),
  line({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'ok' }] } }),
  line({ type: 'assistant', message: { content: [{ type: 'text', text: 'Now checking the second column, which carries the done badge.' }] } }),
].join('\n'));
const run = (input) => spawnSync('node', [path.join(__dirname, 'japanese-guard.js')], { input: JSON.stringify(input), encoding: 'utf8' });

let r = run({ hook_event_name: 'Stop', transcript_path: tr });
assert.strictEqual(r.status, 2); assert.match(r.stderr, /日本語/);
// 2026-11-08に詰まった場面1: 直前の文章が英語でも、ツールは止めない(止めると記録が進まず、全ツールが止まり続けた)。
r = run({ hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: {}, transcript_path: tr });
assert.strictEqual(r.status, 0);
// 詰まった場面2: ターンの途中に英語があっても、最終の返答が日本語なら終われる(過去の文章は書き直せない)。
fs.appendFileSync(tr, '\n' + [
  line({ type: 'assistant', message: { content: [{ type: 'tool_use', name: 'Bash', input: {} }] } }),
  line({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'ok' }] } }),
  line({ type: 'assistant', message: { content: [{ type: 'text', text: '先ほどの英語の文を日本語で書き直します。確認はすべて通りました。' }] } }),
].join('\n'));
assert.strictEqual(run({ hook_event_name: 'Stop', transcript_path: tr }).status, 0);
r = run({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'ls', description: 'List files in directory' }, transcript_path: '/nonexistent' });
assert.strictEqual(r.status, 2); assert.match(r.stderr, /description/);
r = run({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command: 'ls', description: 'ファイルの一覧を出す' }, transcript_path: '/nonexistent' });
assert.strictEqual(r.status, 0);

fs.writeFileSync(tr, [
  line({ type: 'user', message: { role: 'user', content: '質問' } }),
  line({ type: 'assistant', message: { content: [{ type: 'text', text: '日本語で答えます。`src/a.ts` を直しました。' }] } }),
].join('\n'));
assert.strictEqual(run({ hook_event_name: 'Stop', transcript_path: tr }).status, 0);
assert.strictEqual(run({ hook_event_name: 'PreToolUse', tool_name: 'Read', tool_input: {}, transcript_path: tr }).status, 0);
assert.strictEqual(spawnSync('node', [path.join(__dirname, 'japanese-guard.js')], { input: 'not json', encoding: 'utf8' }).status, 0);

// last_assistant_message があれば記録より優先する(記録に最終の返答が入る保証が無いため)。
assert.strictEqual(run({ hook_event_name: 'Stop', transcript_path: tr, last_assistant_message: 'This final answer is written entirely in English and must be blocked.' }).status, 2);
assert.strictEqual(run({ hook_event_name: 'Stop', transcript_path: tr, last_assistant_message: '最終の返答は日本語です。' }).status, 0);

// 同じターンで止めるのは2回まで。3回目は止めずに警告(systemMessage)を出す。
process.env.JAPANESE_GUARD_STATE_DIR = path.join(dir, 'state');
const runS = (input) => spawnSync('node', [path.join(__dirname, 'japanese-guard.js')], { input: JSON.stringify(input), encoding: 'utf8', env: { ...process.env } });
const eng = { hook_event_name: 'Stop', session_id: 's1', transcript_path: tr, last_assistant_message: 'Still answering in English even after being asked to rewrite it.' };
assert.strictEqual(runS(eng).status, 2);
assert.strictEqual(runS(eng).status, 2);
const third = runS(eng);
assert.strictEqual(third.status, 0);
assert.match(JSON.parse(third.stdout).systemMessage, /2回/);
fs.rmSync(dir, { recursive: true });
console.log('japanese-guard: すべて通過');
