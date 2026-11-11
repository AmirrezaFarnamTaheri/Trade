const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../src/gym/ui/models.js'), 'utf8');
const esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const turn = () => new Promise(resolve => setImmediate(resolve));
const event = () => ({ preventDefault() {} });

async function page(complete = async () => ({ text: '<paid response>' })) {
  const nodes = new Map(), calls = [];
  class Node {
    constructor(id, type = '') {
      this.id = id; this.type = type; this.value = ''; this.textContent = '';
      this.disabled = false; this.dataset = {}; this._html = '';
    }
    set innerHTML(html) {
      this._html = html;
      if (this.id === 'models-content') {
        nodes.clear(); nodes.set(this.id, this);
        for (const [, , attrs, id] of html.matchAll(/<([a-z][a-z0-9-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
          const child = new Node(id, attrs.match(/\btype="([^"]+)"/)?.[1]);
          child.disabled = /\bdisabled\b/.test(attrs); nodes.set(id, child);
        }
      }
      if (this.id === 'models-connections' && html.includes('data-secret-keys')) {
        nodes.set('secret-key', new Node('secret-key', 'password'));
      }
      if (this.id === 'models-preset' || this.id === 'models-provider' || this.id === 'models-auth') {
        this.value = html.match(/<option value="([^"]+)"/)?.[1] || '';
      }
    }
    get innerHTML() { return this._html; }
    querySelectorAll() { return [...nodes.values()].filter(node => node.type === 'password'); }
  }
  nodes.set('models-content', new Node('models-content'));
  const context = {
    T: require('./vocabulary.cjs').T, window: {}, clearTimeout, setTimeout,
    document: { documentElement: { lang: 'en' }, getElementById: id => nodes.get(id) || null },
    localStorage: { getItem() { throw new Error('browser storage is forbidden'); }, setItem() { throw new Error('browser storage is forbidden'); } },
  };
  const api = async (_url, options) => {
    const body = JSON.parse(options.body); calls.push(body);
    if (body.action === 'providers') return [{ id: 'openai', name: 'OpenAI', api_key: true, completionSupported: true }];
    if (body.action === 'status') return {
      enabled: true, storage: 'WINDOWS_DPAPI', connections: [{ id: 'main', provider: 'openai', auth: { type: 'api_key', stored: true }, configuredKeys: 1 }],
      presets: [{ id: 'first', connection: 'main', model: 'one' }, { id: 'second', connection: 'main', model: 'two' }],
    };
    if (body.action === 'usage') return { by_model: [] };
    if (body.action === 'complete') return complete(body.value);
    throw new Error('unexpected action: ' + body.action);
  };
  vm.runInNewContext(source, context);
  const mount = async language => {
    context.document.documentElement.lang = language;
    await context.window.gymModels.mount(api, esc);
  };
  await mount('en');
  return { node: id => nodes.get(id), nodes, Node, calls, mount };
}

test('language toggles retain the prompt, chosen preset and paid response while clearing credentials', async () => {
  const p = await page();
  p.node('models-preset').value = 'second';
  p.node('models-prompt').value = 'Explain the recorded risk';
  p.node('models-complete').onsubmit(event()); await turn();
  const result = p.node('models-result').textContent;
  assert.match(result, /<paid response>/);
  p.node('models-prompt').value = 'Unsent next prompt';
  const key = p.node('secret-key'); key.value = 'unsaved-secret';
  const answer = new p.Node('models-answer', 'password'); answer.value = 'login-code'; p.nodes.set(answer.id, answer);
  await p.mount('fa');
  assert.equal(p.node('models-prompt').value, 'Unsent next prompt');
  assert.equal(p.node('models-preset').value, 'second');
  assert.equal(p.node('models-result').textContent, result);
  assert.equal(key.value, ''); assert.equal(answer.value, '');
  assert.equal(p.node('secret-key').value, '');
  await p.mount('en');
  assert.equal(p.node('models-prompt').value, 'Unsent next prompt');
  assert.equal(p.node('models-result').textContent, result);
  assert.equal(p.calls.filter(call => call.action === 'complete').length, 1);
});

test('a language toggle during completion keeps one paid request and renders its response in the current view', async () => {
  let resolve;
  const p = await page(() => new Promise(done => { resolve = done; }));
  p.node('models-preset').value = 'second';
  p.node('models-prompt').value = 'Original prompt';
  const pending = p.node('models-complete').onsubmit(event());
  await p.mount('fa');
  assert.equal(p.node('models-send').disabled, true);
  p.node('models-complete').onsubmit(event());
  assert.equal(p.calls.filter(call => call.action === 'complete').length, 1);
  p.node('models-prompt').value = 'Next unsent prompt';
  resolve({ text: 'Completed once' }); await pending; await turn();
  assert.match(p.node('models-result').textContent, /Completed once/);
  assert.equal(p.node('models-prompt').value, 'Next unsent prompt');
  assert.equal(p.node('models-send').disabled, false);
  await p.mount('en');
  assert.match(p.node('models-result').textContent, /Completed once/);
  assert.equal(p.node('models-preset').value, 'second');
  assert.equal(p.calls.filter(call => call.action === 'complete').length, 1);
});
