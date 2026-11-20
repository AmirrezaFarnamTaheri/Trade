const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {T} = require('./vocabulary.cjs');

function page(api) {
  const nodes = new Map();
  class Node {
    constructor(id) { this.id = id; this.value = id === 'research-action' ? 'register' : ''; this.disabled = false; this.childNodes = []; this.tagName = 'DIV'; this.attributes = {}; this.htmlWrites = 0; }
    get innerHTML() { return this.html || ''; }
    set innerHTML(html) {
      this.html = html; this.htmlWrites++;
      for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) nodes.set(id, new Node(id));
    }
    setAttribute(key, value) { this.attributes[key] = value; }
    getAttribute(key) { return this.attributes[key]; }
    hasAttribute(key) { return key in this.attributes; }
    querySelector() { return this.button ||= new Node(this.id + '-button'); }
    closest() { return this.disclosure ||= {open: true}; }
    insertAdjacentHTML(_position, html) { this.html = (this.html || '') + html; }
    remove() {}
  }
  const node = id => { if (!nodes.has(id)) nodes.set(id, new Node(id)); return nodes.get(id); };
  node('gym-config').textContent = JSON.stringify({resolutions: ['15min', '1day']});
  const context = {T, crypto: {randomUUID: () => 'b'.repeat(32)}, window: {GymReplayChart: {render: () => ''}}, document: {documentElement: {lang: 'en'}, getElementById: node}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../src/gym/ui/research.js'), 'utf8'), context);
  const mount = () => context.window.gymResearch.mount(api, value => String(value ?? ''));
  mount();
  return {node, mount, context};
}
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(setImmediate); };
const submit = node => node.onsubmit({preventDefault() {}, target: node});

test('language switches retain exact drafts, results and the original in-flight action', async () => {
  let resolve, calls = 0;
  const p = page(async () => { calls++; return new Promise(done => { resolve = done; }); });
  const input = p.node('research-action-input'); input.value = '{"cash":"1000.000000000000000001"}';
  const form = p.node('research-action-form');
  const pending = submit(form);
  await submit(form);
  const workbench = p.node('research-workbench'), writes = workbench.htmlWrites;
  p.context.document.documentElement.lang = 'fa'; p.mount();
  assert.equal(p.node('research-action-input'), input);
  assert.equal(input.value, '{"cash":"1000.000000000000000001"}');
  assert.equal(form.querySelector().disabled, true);
  assert.equal(workbench.htmlWrites, writes);
  assert.equal(calls, 1);
  resolve({receipt: 'a'.repeat(64), cash: '1000.000000000000000001'}); await pending;
  assert.match(p.node('research-action-result').textContent, /1000\.000000000000000001/);
  assert.equal(p.node('research-action-status').textContent, T.fa.rsRequestCompleted);
  assert.equal(form.querySelector().disabled, false);
});

test('language changes translate interface labels without touching editable values or raw receipts', () => {
  const p = page(async () => ({}));
  const label = {nodeType: 3, nodeValue: '  ' + T.en.rsWorkflow + '  '};
  const raw = {nodeType: 3, nodeValue: T.en.rsWorkflow};
  const note = {nodeType: 3, nodeValue: T.en.rsWorking};
  p.node('research-workbench').childNodes = [label, {tagName: 'PRE', childNodes: [raw]}, {tagName: 'P', hasAttribute: key => key === 'data-raw', childNodes: [note]}];
  p.node('research-action-input').value = T.en.rsWorkflow;
  p.context.document.documentElement.lang = 'fa'; p.mount();
  assert.equal(label.nodeValue, '  ' + T.fa.rsWorkflow + '  ');
  assert.equal(raw.nodeValue, T.en.rsWorkflow);
  assert.equal(note.nodeValue, T.en.rsWorking);
  assert.equal(p.node('research-action-input').value, T.en.rsWorkflow);
});

test('replay cursor and uncertain annotation identity survive language changes without another read', async () => {
  const calls = [];
  const p = page(async (_path, options) => {
    const body = JSON.parse(options.body); calls.push(body);
    if (body.action === 'replay') return {total: 3, run_id: body.value.run_id, outputs_digest: 'c'.repeat(64), quote_currency: 'USDT', decisions: [{index: body.value.limit - 1, known_at_decision: {t: '2026-11-16T00:00:00Z', action: 'WAIT', feature_values: {close: '1'}, position_known: {state: 'HELD_DUST', asset: 'BTC', sellable_quantity_at_bid: '0'}}}]};
    if (body.action === 'annotation-list') return {through: 0, next_after: null, events: []};
    if (body.action === 'annotation-add') throw new Error('Receipt unavailable');
    return {};
  });
  p.node('replay-run').value = 'a'.repeat(16); submit(p.node('replay-form')); await settle();
  assert.ok(p.node('replay-decision').innerHTML.includes(T.en.paperPositionHELD_DUST));
  p.node('replay-next').onclick({target: p.node('replay-next')}); await settle();
  assert.equal(calls.filter(row => row.action === 'replay').at(-1).value.limit, 2);
  const note = p.node('replay-annotation-text'); note.value = 'Keep this exact note';
  submit(p.node('replay-annotation-form')); await settle();
  const first = calls.find(row => row.action === 'annotation-add');
  const reads = calls.length;
  p.context.document.documentElement.lang = 'fa'; p.mount();
  assert.equal(calls.length, reads);
  assert.equal(p.node('replay-annotation-text'), note);
  assert.equal(note.value, 'Keep this exact note');
  submit(p.node('replay-annotation-form')); await settle();
  const retry = calls.filter(row => row.action === 'annotation-add').at(-1);
  assert.equal(retry.value.request_id, first.value.request_id);
  assert.equal(retry.value.decision_index, 1);
  p.node('replay-next').onclick({target: p.node('replay-next')}); await settle();
  assert.equal(calls.filter(row => row.action === 'replay').at(-1).value.limit, 3);
  assert.ok(p.node('replay-decision').innerHTML.includes(T.fa.paperPositionHELD_DUST));
});
