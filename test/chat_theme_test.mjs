import { test } from 'node:test';
import assert from 'node:assert/strict';
import { applyEmbedTheme } from '../chat/theme.mjs';
const palette = { bg: 'rgb(0, 0, 0)', fg: 'rgb(0, 255, 0)', muted: 'rgb(0, 255, 0)', input: 'rgb(20, 20, 20)', border: 'rgb(50, 50, 50)', accent: 'rgb(0, 255, 0)', backgroundImage: 'none' };
const css = { supports: (property, value) => property === 'color' ? /^rgb\([\d, ]+\)$/.test(value) : value === 'none' };
function fixture() { const values = new Map(); return { values, style: { setProperty: (key, value) => values.set(key, value) } }; }
test('valid parent colors are applied without changing authentication or connection state', () => {
 const root = fixture();
 assert.equal(applyEmbedTheme(root, { type: 'conversation-theme', palette }, css), true);
 assert.equal(root.values.get('--embed-fg'), palette.fg);
 assert.equal(root.values.size, 7);
});
test('invalid colors, missing values and image URLs are rejected without partial updates', () => {
 for (const invalid of [{ ...palette, fg: 'url(https://example.com)' }, { ...palette, bg: null }, { ...palette, backgroundImage: 'linear-gradient(red, blue), url(https://example.com)' }]) {
  const root = fixture();
  assert.equal(applyEmbedTheme(root, { type: 'conversation-theme', palette: invalid }, css), false);
  assert.equal(root.values.size, 0);
 }
});
test('unrelated control messages cannot apply a palette', () => {
 const root = fixture();
 assert.equal(applyEmbedTheme(root, { type: 'conversation-start', palette }, css), false);
 assert.equal(root.values.size, 0);
});
