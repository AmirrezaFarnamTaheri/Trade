import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';
import { State } from '../state.mjs';
import { ModelControl } from '../control.mjs';
import { validate, emptyConfig } from '../config.mjs';

async function fixture(t) {
  const home = await mkdtemp(join(tmpdir(), 'gym-model-control-'));
  // Test-only reversible envelope verifies the storage contract without using account credentials.
  const state = await new State(home, { seal: async b => Buffer.from(b.toString('base64')), unseal: async b => Buffer.from(b.toString(), 'base64') }).init();
  const control = new ModelControl(state);
  t.after(async () => { control.close(); await rm(home, { force: true, recursive: true }); });
  return { home, state, control, call: (action, value) => control.request({ action, value }) };
}

test('private API key pools persist without exporting keys and stay scoped to provider and connection', async t => {
  const { call, state, home } = await fixture(t);
  const c = { id: 'primary', provider: 'openai', auth: { type: 'api_key', env: [], stored: true } };
  await call('connection', c);
  await call('keys', { connection: c.id, keys: ['synthetic-test-key'] });
  assert.deepEqual(await state.apiKeys(c), ['synthetic-test-key']);
  assert.deepEqual(await state.apiKeys({ ...c, id: 'other' }), []);
  assert.deepEqual(await state.apiKeys({ ...c, provider: 'anthropic' }), []);
  const status = await call('status');
  assert.equal(status.connections[0].configuredKeys, 1);
  assert.equal(status.enabled, false);
  assert.equal(JSON.stringify(status).includes('synthetic-test-key'), false);
  assert.equal((await readFile(join(home, 'state.sqlite'))).includes(Buffer.from('synthetic-test-key')), false);
  assert.equal((await readFile(join(home, 'config.json'), 'utf8')).includes('synthetic-test-key'), false);
  await call('keys', { connection: c.id, keys: [] });
  assert.deepEqual(await state.apiKeys(c), []);
});

test('web control rejects malformed keys, unknown actions, changed connection IDs and inline credentials', async t => {
  const { call } = await fixture(t);
  const c = { id: 'main', provider: 'anthropic', auth: { type: 'api_key', env: [], stored: true } };
  await call('connection', c);
  for (const keys of [null, [''], ['bad\nkey'], ['x', 'x'], ['a'.repeat(16385)]]) {
    await assert.rejects(call('keys', { connection: c.id, keys }));
  }
  await assert.rejects(call('connection', { ...c, provider: 'openai' }), /connection_exists/);
  await assert.rejects(call('shell', 'anything'));
  await assert.rejects(call('enabled', 'true'));
  await assert.rejects(call('complete', { preset: 'unknown', prompt: 'never sent' }), /gateway_disabled/);
  assert.throws(() => validate({ ...emptyConfig(), connections: [{ ...c, auth: { type: 'api_key', env: [], stored: true, key: 'inline' } }] }));
});

test('model catalogs and portable merge preserve disabled state without credentials', async t => {
  const { call } = await fixture(t);
  const models = await call('catalog', 'openai');
  assert.ok(models.length > 0);
  await call('connection', { id: 'main', provider: 'openai', auth: { type: 'api_key', env: [], stored: true } });
  await call('sync', 'main');
  const status = await call('status');
  assert.ok(status.presets.length > 0);
  await call('import', { ...emptyConfig(), enabled: true });
  assert.equal((await call('status')).enabled, false);
  await assert.rejects(call('reply', { id: 'missing', prompt: 'missing', answer: 'secret' }), /unknown_login/);
});

test('installed SDK browser login is cancellable and prevents credential/config changes while pending', async t => {
  const { call } = await fixture(t);
  await call('connection', { id: 'claude', provider: 'anthropic', auth: { type: 'oauth' } });
  const session = await call('login', 'claude');
  for (let i = 0; i < 50; i++) {
    const view = await call('session', session.id);
    if (view.prompt || view.state !== 'PENDING') break;
    await sleep(10);
  }
  const view = await call('session', session.id);
  assert.equal(view.state, 'PENDING');
  assert.equal(view.prompt.type, 'select');
  await assert.rejects(call('enabled', true), /login_in_progress/);
  await assert.rejects(call('reply', { id: session.id, prompt: 'stale', answer: 'browser' }), /login_not_waiting/);
  await call('cancel', { id: session.id });
  for (let i = 0; i < 50 && (await call('session', session.id)).state === 'PENDING'; i++) await sleep(10);
  assert.equal((await call('session', session.id)).state, 'CANCELLED');
  assert.equal((await call('status')).connections[0].loggedIn, false);
});

test('stdio host correlates bounded control requests without exposing provider errors', async t => {
  const { home } = await fixture(t);
  const child = spawn(process.execPath, [join(import.meta.dirname, '../host.mjs')], {
    env: { ...process.env, GYM_MODEL_HOME: home }, stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true,
  });
  t.after(() => child.kill());
  let output = '';
  child.stdout.on('data', chunk => { output += chunk; });
  child.stdin.write(JSON.stringify({ id: 1, action: 'providers' }) + '\n');
  child.stdin.write(JSON.stringify({ id: 2, action: 'status' }) + '\n');
  const deadline = Date.now() + 15000;
  while (output.split('\n').length < 3 && Date.now() < deadline) await sleep(10);
  const replies = output.trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(replies.map(r => r.id), [1, 2]);
  assert.ok(replies[0].result.some(p => p.id === 'openai' && p.oauth));
  assert.equal(replies[1].result.enabled, false);
  child.stdin.end();
});
