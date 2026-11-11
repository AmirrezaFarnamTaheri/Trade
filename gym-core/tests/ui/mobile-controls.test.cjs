const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('market selection shares the mobile 44px control floor', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../src/gym/ui/styles.css'), 'utf8');
  const mobile = css.split('@media (max-width: 600px)')[1].split('@media')[0];
  assert.match(mobile, /[^{}]*\.symbol-button[^{}]*\{\s*min-height:\s*44px;/);
});
