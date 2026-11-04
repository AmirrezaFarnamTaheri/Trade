const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const {test} = require('node:test');
const window = {};
runInNewContext(readFileSync('src/gym/ui/replay-chart.js', 'utf8'), {window});
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const row = (index, minute, start, end) => ({index, known_at_decision: {t: `2026-10-29T09:${minute}:00Z`, close: '70000', action: '<unsafe>', bar_known: {start, end}}});

test('chart preserves gaps, flat prices, escaped labels and excludes future decisions', () => {
  const rows = [row(0, '01', 'a', 'b'), row(1, '02', 'b', 'c'), row(2, '05', 'd', 'e'), row(3, '06', 'e', 'f')];
  const html = window.GymReplayChart.render(rows, 2, 'USDT', esc, false);
  assert.equal((html.match(/<path /g) || []).length, 1);
  assert.equal((html.match(/<circle /g) || []).length, 3);
  assert.ok(!html.includes('<unsafe>') && html.includes('&lt;unsafe&gt;'));
  assert.ok(!html.includes('NaN') && !html.includes('Infinity'));
  assert.ok(html.includes('role="button"') && html.includes('aria-current="step"'));
  assert.ok(!html.includes('data-replay-index="3"'));
});

test('empty and non-finite prices do not manufacture chart values', () => {
  assert.ok(!window.GymReplayChart.render([], 0, 'USDT', esc, true).includes('<svg'));
  const invalid = row(0, '01', 'a', 'b'); invalid.known_at_decision.close = 'Infinity';
  assert.ok(!window.GymReplayChart.render([invalid], 0, 'USDT', esc, false).includes('<svg'));
  const old = [row(0, '01'), row(1, '02')];
  old.forEach(point => { delete point.known_at_decision.bar_known; });
  assert.ok(!window.GymReplayChart.render(old, 1, 'USDT', esc, false).includes('<path'));
});
