const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { T } = require('./vocabulary.cjs');

async function storageLabel(lang, storage, legacy) {
  const nodes = new Map();
  class Node {
    constructor(id) { this.id = id; this.value = ''; this.textContent = ''; this.dataset = {}; }
    set innerHTML(html) {
      this.html = html;
      if (this.id === 'models-content') {
        for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(id, new Node(id));
      }
      if (html.includes('<option')) this.value = html.match(/value="([^"]+)"/)?.[1] || '';
    }
    get innerHTML() { return this.html || ''; }
  }
  nodes.set('models-content', new Node('models-content'));
  const context = { T, window: {}, document: { documentElement: { lang }, getElementById: id => nodes.get(id) } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../src/gym/ui/models.js'), 'utf8'), context);
  const api = async (_url, { body }) => {
    switch (JSON.parse(body).action) {
      case 'providers': return [{ id: 'openai', name: 'OpenAI', api_key: true, oauth: false, completionSupported: true }];
      case 'status': return { enabled: false, connections: [], presets: [], storage, legacy_plaintext_possible: legacy };
      case 'usage': return { by_model: [] };
    }
  };
  await context.window.gymModels.mount(api, String);
  return nodes.get('models-storage').textContent;
}

test('credential labels name new-write protection and retain the legacy warning in both languages', async () => {
  for (const lang of ['en', 'fa']) {
    for (const [storage, key] of [
      ['WINDOWS_USER_DPAPI', 'modelsStorageDpapi'],
      ['PRIVATE_FILE_PASSPHRASE_SEALED', 'modelsStorageSealed'],
      ['PRIVATE_FILE_PLAINTEXT', 'modelsPlaintext'],
      ['CREDENTIAL_PROTECTION_UNAVAILABLE', 'modelsStorageUnavailable'],
    ]) {
      const legacy = storage !== 'WINDOWS_USER_DPAPI';
      const label = await storageLabel(lang, storage, legacy);
      assert.ok(T[lang][key], `Missing ${lang} ${key}`);
      assert.ok(label.includes(T[lang][key]), label);
      assert.equal(label.includes(T[lang].modelsStorageLegacy), legacy, label);
      if (storage === 'PRIVATE_FILE_PASSPHRASE_SEALED') assert.ok(!label.includes(T[lang].modelsPlaintext));
    }
  }
});
