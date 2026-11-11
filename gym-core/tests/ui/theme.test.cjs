const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../src/gym/ui/workspace-utils.js'), 'utf8');

function themeFor(systemDark, stored) {
  const storage = new Map(stored ? [['theme', stored]] : []);
  const context = {
    document: { getElementById: () => null },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    matchMedia: query => ({ matches: systemDark && query === '(prefers-color-scheme: dark)' }),
    T: { en: {}, fa: {} },
  };
  vm.runInNewContext(source + '\n;globalThis.__theme = theme;', context);
  return context.__theme;
}

test('first visit follows the system colour scheme', () => {
  assert.equal(themeFor(true, null), 'dark');
  assert.equal(themeFor(false, null), 'light');
});

test('a remembered choice wins over the system', () => {
  assert.equal(themeFor(true, 'light'), 'light');
  assert.equal(themeFor(false, 'dark'), 'dark');
});
