const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function page(api, demo = false) {
  const ids = ['native-review-form', 'native-review-context', 'native-review-submit', 'native-review-result', 'native-review-input'];
  const nodes = Object.fromEntries(ids.map(id => [id, {disabled:false, textContent:'', value:'', listeners:{}, addEventListener(name, handler) {this.listeners[name] = handler;}}]));
  const context = {T: require('./vocabulary.cjs').T, window:{}, document:{getElementById:id => nodes[id], documentElement:{lang:'en'}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../src/gym/ui/native-review.js'), 'utf8'), context);
  context.window.gymNativeReview.mount(api, demo);
  return nodes;
}
test('opening the workflow never calls the service and DEMO cannot start a helper', () => {
  const calls = [];
  const nodes = page((...args) => calls.push(args), true);
  assert.equal(calls.length, 0);
  assert.equal(nodes['native-review-context'].disabled, true);
  assert.equal(nodes['native-review-submit'].disabled, true);
  assert.match(nodes['native-review-result'].textContent, /disabled in DEMO/);
});
test('explicit actions prevent duplicate pending calls and replace old receipts on failure', async () => {
  let finish;
  const calls = [];
  const nodes = page((...args) => {calls.push(args);return new Promise(resolve => {finish = resolve;});});
  assert.equal(calls.length, 0);
  const pending = nodes['native-review-context'].listeners.click();
  await nodes['native-review-context'].listeners.click();
  assert.equal(calls.length, 1);
  assert.equal(nodes['native-review-submit'].disabled, true);
  finish({state:'STATUS',funded_authority:false,order_submitted:false});
  await pending;
  assert.equal(nodes['native-review-submit'].disabled, false);
  assert.match(nodes['native-review-result'].textContent, /STATUS/);
  nodes['native-review-input'].value = JSON.stringify({action:'prepare',client_id:'intent-1',expected_sequence:'2'});
  const mutation = nodes['native-review-form'].listeners.submit({preventDefault(){}});
  assert.equal(calls[1][1].method, 'POST');
  assert.deepEqual(JSON.parse(calls[1][1].body), {action:'prepare',client_id:'intent-1',expected_sequence:'2'});
  finish({state:'APPROVAL_RECORDED',funded_authority:true,order_submitted:false});
  await mutation;
  assert.match(nodes['native-review-result'].textContent, /unacknowledged/);
  assert.doesNotMatch(nodes['native-review-result'].textContent, /STATUS|APPROVAL_RECORDED/);
});
