#!/usr/bin/env node
// 利用者の指定(2026-11-08)「英語でやりとりすんな」「それもHooksで縛れ」。
// 利用者に見える文章を日本語に縛る。Stop・PreToolUseのフックとして ~/.claude/settings.json から呼ぶ。
//   Stop: 今のターンで書いた文章のうち、英語のものがあれば止めて日本語で書き直させる。
//   PreToolUse: 直前に書いた文章、またはBashの説明(description)が英語なら、ツールの実行を止める。
// コードブロック・インラインコード・URL・パス・識別子は判定から外す。止めるときは終了コード2で理由を返す。
'use strict';
const fs = require('node:fs');

function stripNonProse(text) {
  return String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`\n]*`/g, ' ')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/\S*[\/\\._=:@#$<>{}\[\]()|]\S*/g, ' ');
}

function isEnglish(text) {
  const prose = stripNonProse(text);
  const jp = (prose.match(/[぀-ヿ㐀-鿿ｦ-ﾟ]/g) || []).length;
  const latin = (prose.match(/[A-Za-z]/g) || []).length;
  if (latin < 30) return false;
  return jp < latin * 0.25;
}

function readTranscript(path) {
  try {
    return fs.readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch { return []; }
}

function isRealUserMessage(entry) {
  if (entry.type !== 'user' || !entry.message) return false;
  const c = entry.message.content;
  if (typeof c === 'string') return true;
  return Array.isArray(c) && c.some((b) => b && b.type === 'text');
}

// 今のターンの最終の返答(最後のツール呼び出しより後の文章)。
// 過去の文章は書き直せないので、ターン全体を見ると一度英語を書いたターンが終われなくなる(2026-11-08に実際に詰まった)。
function finalTexts(entries) {
  let start = 0;
  for (let i = entries.length - 1; i >= 0; i--) { if (isRealUserMessage(entries[i])) { start = i + 1; break; } }
  let final = [];
  for (const e of entries.slice(start)) {
    if (e.type !== 'assistant' || !e.message || !Array.isArray(e.message.content)) continue;
    for (const b of e.message.content) {
      if (b && b.type === 'tool_use') final = [];
      if (b && b.type === 'text' && b.text) final.push(b.text);
    }
  }
  return final;
}

function excerpt(t) { return String(t).replace(/\s+/g, ' ').slice(0, 80); }

const MAX_BLOCKS_PER_TURN = 2;
// 状態はリポジトリの外に置く(このファイルは ~/.claude/hooks からのリンクで呼ばれ、__dirname はリポジトリの中になる)。
const STATE_DIR = process.env.JAPANESE_GUARD_STATE_DIR || require('node:path').join(require('node:os').homedir(), '.claude', 'hooks', 'state');

// ターンごとに止めた回数を数える。ターンは「セッション + 利用者の発言の数」で区別する。
function countBlock(input) {
  const entries = input.transcript_path ? readTranscript(input.transcript_path) : [];
  const turn = String(input.session_id || 'nosession') + ':' + entries.filter(isRealUserMessage).length;
  const file = require('node:path').join(STATE_DIR, 'japanese-guard-' + String(input.session_id || 'nosession').replace(/[^A-Za-z0-9_-]/g, '_') + '.json');
  let state = {};
  try { state = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { state = {}; }
  const count = state.turn === turn ? (state.count || 0) + 1 : 1;
  try { fs.mkdirSync(STATE_DIR, { recursive: true }); fs.writeFileSync(file, JSON.stringify({ turn, count })); } catch { /* 数えられなくても判定は続ける */ }
  return count;
}

function decide(input) {
  const event = input.hook_event_name;
  if (event === 'Stop') {
    // Stopの時点で記録に最終の返答が入っている保証は無い。公式の入力欄 last_assistant_message を優先する(Codexの評価、2026-11-08)。
    let finals;
    if (typeof input.last_assistant_message === 'string' && input.last_assistant_message) finals = [input.last_assistant_message];
    else finals = finalTexts(input.transcript_path ? readTranscript(input.transcript_path) : []);
    const bad = finals.filter(isEnglish);
    if (!bad.length) return null;
    // 同じターンで止めるのは2回まで。超えたら止めずに利用者へ警告を出す(Museの評価: 回数の上限が無いと終わらないループになる)。
    if (countBlock(input) > MAX_BLOCKS_PER_TURN) return { warnOnly: '[japanese-guard] 日本語への書き直しを' + MAX_BLOCKS_PER_TURN + '回求めても英語が残ったため、止めずに通しました(' + excerpt(bad[bad.length - 1]) + ')' };
    return '[japanese-guard] 最終の返答に英語の文章があります(' + excerpt(bad[bad.length - 1]) + ')。利用者の指定により、利用者に見える文章はすべて日本語で書く。日本語で書き直すこと。';
  }
  // PreToolUseでは直前の文章を見ない。記録が1つ遅れて見えるうえ、止めたツール呼び出しでは記録が進まず、全ツールが止まり続けた(2026-11-08)。
  if (event === 'PreToolUse') {
    const desc = input.tool_input && input.tool_input.description;
    if (input.tool_name === 'Bash' && desc && isEnglish(desc + ' ' + desc + ' ' + desc)) return '[japanese-guard] Bashの説明(description)が英語です(' + excerpt(desc) + ')。日本語で書き直して実行し直すこと。';
  }
  return null;
}

module.exports = { isEnglish, finalTexts, decide };

if (require.main === module) {
  let raw = '';
  process.stdin.on('data', (c) => { raw += c; });
  process.stdin.on('end', () => {
    let input;
    try { input = JSON.parse(raw); } catch { process.exit(0); }
    const reason = decide(input);
    if (!reason) process.exit(0);
    if (typeof reason === 'object' && reason.warnOnly) {
      process.stdout.write(JSON.stringify({ systemMessage: reason.warnOnly }));
      process.exit(0);
    }
    process.stderr.write(reason + '\n');
    process.exit(2);
  });
}
