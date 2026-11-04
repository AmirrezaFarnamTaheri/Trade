import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile, symlink, chmod } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { setTimeout as sleep } from 'node:timers/promises';
import { State } from '../state.mjs';
import { validate, parseConfig, emptyConfig, syncPresets, mergePresets, catalog } from '../config.mjs';
import { complete, oauthModels } from '../runtime.mjs';

const identity = { seal: async b => b, unseal: async b => b, allowLoopback: true };
const env = { KEY_A: 'test-secret-a', KEY_B: 'test-secret-b', KEY_DUP: 'test-secret-a' };
function configuration(baseURL, protocol = 'openai-completions') {
  return validate({ schema: 1, enabled: true, connections: [{ id: 'local', provider: 'test', protocol, baseURL, auth: { type: 'api_key', env: ['KEY_A', 'KEY_DUP', 'KEY_B'] } }], presets: [{ id: 'research', name: 'My research', connection: 'local', model: 'fixed-model', maxTokens: 128, temperature: 0.2 }] }, { allowLoopback: true });
}
function sse(res, events) {
  res.writeHead(200, { 'content-type': 'text/event-stream' });
  for (const e of events) res.write(typeof e === 'string' ? e : `data: ${JSON.stringify(e)}\n\n`);
  res.end();
}
function openai(res, usage = {}) {
  sse(res, [
    { id: 'test', object: 'chat.completion.chunk', choices: [{ index: 0, delta: { role: 'assistant', content: 'Advisory only.' }, finish_reason: null }] },
    { id: 'test', object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 3, completion_tokens: 4, total_tokens: 7, ...usage } },
    'data: [DONE]\n\n',
  ]);
}
function anthropic(res) {
  const events = [
    { type: 'message_start', message: { id: 'msg_test', type: 'message', role: 'assistant', model: 'fixed-model', content: [], stop_reason: null, usage: { input_tokens: 3, output_tokens: 0 } } },
    { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } },
    { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'Advisory only.' } },
    { type: 'content_block_stop', index: 0 },
    { type: 'message_delta', delta: { stop_reason: 'end_turn', stop_sequence: null }, usage: { output_tokens: 4 } },
    { type: 'message_stop' },
  ];
  sse(res, events.map(e => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`));
}
function error(res, status, code = 'rejected', headers = {}) {
  res.writeHead(status, { 'content-type': 'application/json', ...headers });
  res.end(JSON.stringify({ error: { code, type: code, message: 'test-secret-a test-secret-b provider internal details' } }));
}
async function fixture(t, handler = (_, res) => openai(res), protocol) {
  const home = await mkdtemp(join(tmpdir(), 'gym-gateway-'));
  // mkdtemp inherits permissive Windows ACLs; State installs a private DACL before use.
  const state = await new State(home, identity).init();
  const calls = [];
  const server = createServer(async (req, res) => {
    let bytes = ''; for await (const b of req) bytes += b;
    calls.push({ path: req.url, auth: req.headers.authorization || req.headers['x-api-key'], body: JSON.parse(bytes) });
    handler(req, res, calls.length);
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(async () => { server.closeAllConnections(); await new Promise(r => server.close(r)); await rm(home, { recursive: true, force: true }); });
  const config = configuration(`http://127.0.0.1:${server.address().port}/v1`, protocol);
  return { home, state, server, config, calls };
}
function run(args, { home, input = '', extraEnv = {} } = {}) {
  const child = spawn(process.execPath, args, { env: { ...process.env, ...env, GYM_MODEL_HOME: home, GYM_MODEL_ALLOW_LOOPBACK_HTTP: '1', ...extraEnv }, stdio: ['pipe', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  child.stdout.on('data', b => { stdout += b; }); child.stderr.on('data', b => { stderr += b; });
  child.stdin.on('error', () => {}); child.stdin.end(input);
  return new Promise((resolvePromise, reject) => { child.on('error', reject); child.on('close', code => resolvePromise({ code, stdout, stderr })); });
}
const cli = resolve(import.meta.dirname, '../gateway.mjs');
const worker = resolve(import.meta.dirname, 'refresh-worker.mjs');

test('default disabled and strict trust-boundary validation', () => {
  assert.equal(emptyConfig().enabled, false);
  const base = configuration('https://example.invalid/v1');
  const bad = [
    { ...base, surprise: true }, { ...base, enabled: 'true' }, { ...base, schema: 2 },
    { ...base, connections: [base.connections[0], base.connections[0]] },
    { ...base, presets: [base.presets[0], base.presets[0]] },
    { ...base, policy: { maxAttempts: 4 } }, { ...base, policy: { timeoutMs: Infinity } },
    { ...base, presets: [{ ...base.presets[0], temperature: NaN }] },
    { ...base, presets: [{ ...base.presets[0], maxTokens: 0 }] },
    { ...base, presets: [{ ...base.presets[0], tools: [] }] },
    ...['http://example.invalid/v1', 'https://u:p@example.invalid', 'https://example.invalid/?key=secret', 'https://example.invalid/#frag'].map(baseURL => ({ ...base, connections: [{ ...base.connections[0], baseURL }] })),
    ...[{ type: 'api_key', key: 'INLINE', env: ['KEY_A'] }, { type: 'api_key', env: ['KEY_A'], command: 'anything' }, { type: 'oauth', access: 'INLINE' }].map(auth => ({ ...base, connections: [{ ...base.connections[0], auth }] })),
  ];
  for (const c of bad) assert.throws(() => validate(c));
  const anthropicConfig = configuration('https://example.invalid/v1', 'anthropic-messages');
  anthropicConfig.presets[0].temperature = 1.1;
  assert.throws(() => validate(anthropicConfig));
  assert.throws(() => parseConfig(Buffer.from('{')));
  assert.throws(() => parseConfig(Buffer.alloc(1024 * 1024 + 1)));
  const disabled = { ...base }; delete disabled.enabled;
  assert.equal(validate(disabled).enabled, false);
});

test('actual OpenAI SDK: stable model/endpoint, no tools, usage, unique-key round robin survives fresh instances', async t => {
  const f = await fixture(t);
  for (let i = 0; i < 4; i++) {
    const state = i ? await new State(f.home, identity).init() : f.state;
    const result = await complete(state, f.config, 'research', { prompt: 'Assess risk' }, { env });
    assert.equal(result.text, 'Advisory only.'); assert.equal(result.mode, 'RESEARCH_ONLY'); assert.equal(result.funded_authority, false);
    assert.equal(result.usage.input, 3); assert.equal(result.usage.output, 4);
    assert.equal(result.usage.cost, null); assert.equal(result.usage.costSource, 'UNKNOWN');
    assert.deepEqual(result.model.metadata, { source: 'UNKNOWN', providerVerified: false, contextWindow: null, maxOutputTokens: null, reasoning: null, input: null });
    assert.equal(result.model.requestOutputTokens, 128); assert.equal(result.model.gatewayOutputCeiling, 65536);
  }
  assert.deepEqual(f.calls.map(c => c.auth), ['Bearer test-secret-a', 'Bearer test-secret-b', 'Bearer test-secret-a', 'Bearer test-secret-b']);
  for (const call of f.calls) { assert.equal(call.path, '/v1/chat/completions'); assert.equal(call.body.model, 'fixed-model'); assert.equal(call.body.tools, undefined); assert.equal(call.body.max_tokens ?? call.body.max_completion_tokens, 128); }
});

test('built-in SDK catalog prices are estimates; custom endpoints cannot inherit them by model name', async t => {
  const f = await fixture(t, (_, res) => anthropic(res), 'anthropic-messages');
  const model = catalog.getModels('anthropic').find(m => m.api === 'anthropic-messages' && m.cost.input > 0 && m.cost.output > 0);
  assert.ok(model);
  const config = structuredClone(f.config);
  config.connections[0].provider = 'anthropic';
  config.presets[0].model = model.id;
  const custom = await complete(f.state, validate(config, { allowLoopback: true }), 'research', { prompt: 'risk' }, { env });
  assert.equal(custom.usage.cost, null); assert.equal(custom.usage.costSource, 'UNKNOWN');
  assert.equal(custom.model.metadata.contextWindow, null);

  const localURL = `${f.config.connections[0].baseURL}/messages`;
  const realFetch = globalThis.fetch;
  // Exercise the built-in SDK route while sending every request exclusively to the local fixture.
  t.mock.method(globalThis, 'fetch', (_url, init) => realFetch(localURL, init));
  delete config.connections[0].protocol; delete config.connections[0].baseURL;
  const result = await complete(f.state, validate(config), 'research', { prompt: 'risk' }, { env });
  assert.equal(result.usage.costSource, 'SDK_CATALOG_ESTIMATE');
  assert.equal(result.usage.cost.input, (model.cost.input / 1000000) * 3);
  assert.equal(result.usage.cost.output, (model.cost.output / 1000000) * 4);
  assert.ok(result.usage.cost.total > 0);
  assert.deepEqual(result.model.metadata, { source: 'SDK_CATALOG', providerVerified: false, contextWindow: model.contextWindow, maxOutputTokens: model.maxTokens, reasoning: model.reasoning, input: model.input });
  assert.equal(f.calls.length, 2);
});

test('provider-reported total does not fabricate a price breakdown for custom models', async t => {
  const f = await fixture(t, (_, res) => openai(res, { cost: 0.023, is_byok: false }));
  f.config.connections[0].provider = 'openrouter';
  const result = await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  assert.equal(result.usage.costSource, 'PROVIDER_REPORTED');
  assert.deepEqual(result.usage.cost, { total: 0.023, totalFromProvider: true });
  assert.equal(result.model.metadata.source, 'UNKNOWN');
  assert.equal(f.calls.length, 1);
});

test('actual OpenAI Responses SDK completion and fixed endpoint', async t => {
  const item = { id: 'msg_test', type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Advisory only.', annotations: [] }], status: 'completed' };
  const f = await fixture(t, (_, res) => sse(res, [
    { type: 'response.created', response: { id: 'resp_test' } },
    { type: 'response.output_item.added', output_index: 0, item: { ...item, content: [] } },
    { type: 'response.output_text.delta', output_index: 0, content_index: 0, delta: 'Advisory only.' },
    { type: 'response.output_item.done', output_index: 0, item },
    { type: 'response.completed', response: { id: 'resp_test', status: 'completed', output: [item], usage: { input_tokens: 3, output_tokens: 4, total_tokens: 7, input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 0 } } } },
  ]), 'openai-responses');
  const result = await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  assert.equal(result.text, 'Advisory only.'); assert.equal(result.usage.input, 3); assert.equal(result.usage.output, 4);
  assert.equal(f.calls[0].path, '/v1/responses'); assert.equal(f.calls[0].body.model, 'fixed-model'); assert.equal(f.calls[0].body.tools, undefined);
});

test('actual Anthropic SDK completion and usage', async t => {
  const f = await fixture(t, (_, res) => anthropic(res), 'anthropic-messages');
  const result = await complete(f.state, f.config, 'research', { prompt: 'Assess risk' }, { env });
  assert.equal(result.text, 'Advisory only.'); assert.equal(result.usage.input, 3); assert.equal(result.usage.output, 4);
  assert.equal(f.calls[0].body.model, 'fixed-model'); assert.equal(f.calls[0].auth, 'test-secret-a'); assert.equal(f.calls[0].body.tools, undefined);
});

test('429 cooldown persists, genuine Retry-After prevents early reuse and SDK retries are off', async t => {
  const f = await fixture(t, (_, res) => error(res, 429, 'rate_limit_exceeded', { 'retry-after': '3600' }));
  await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env }), /pool_exhausted/);
  assert.equal(f.calls.length, 2);
  const fresh = await new State(f.home, identity).init();
  await assert.rejects(complete(fresh, f.config, 'research', { prompt: 'risk' }, { env }), /pool_exhausted/);
  assert.equal(f.calls.length, 2);
  const row = await f.state.tx(db => db.prepare('SELECT value FROM pools').get());
  for (const h of Object.values(JSON.parse(row.value).health)) assert.ok(h.until > Date.now() + 3500000);
});

test('auth-invalid evicts key; changed values reset health and removed/empty pools discard it', async t => {
  const f = await fixture(t, (req, res) => req.headers.authorization === 'Bearer test-secret-a' ? error(res, 401, 'invalid_api_key') : openai(res));
  await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  assert.deepEqual(f.calls.map(c => c.auth), ['Bearer test-secret-a', 'Bearer test-secret-b', 'Bearer test-secret-b']);
  await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env: {} }), /no_environment_keys/);
  const row = await f.state.tx(db => db.prepare('SELECT value FROM pools').get());
  assert.deepEqual(JSON.parse(row.value).health, {});
  await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env: { KEY_A: 'new-value' } });
  assert.equal(f.calls.at(-1).auth, 'Bearer new-value');
});

test('quota-coded 403 rotates but permission 403 and permanent 400 are fatal and secret-free', async t => {
  const f = await fixture(t, (_, res, n) => n === 1 ? error(res, 403, 'insufficient_quota') : openai(res));
  await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  assert.equal(f.calls.length, 2);
  for (const [status, code] of [[403, 'permission_denied'], [400, 'invalid_request_error']]) {
    const g = await fixture(t, (_, res) => error(res, status, code));
    await assert.rejects(complete(g.state, g.config, 'research', { prompt: 'risk' }, { env }), e => e.message === 'provider_rejected' && !e.message.includes('test-secret'));
    assert.equal(g.calls.length, 1);
  }
});

test('transient 5xx has three actual requests maximum', async t => {
  const f = await fixture(t, (_, res) => error(res, 503));
  await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env }), /attempts_exhausted/);
  assert.equal(f.calls.length, 3);
});

test('transient network failure retries within budget', async t => {
  const f = await fixture(t, (req, res, n) => n === 1 ? req.socket.destroy() : openai(res));
  const result = await complete(f.state, f.config, 'research', { prompt: 'risk' }, { env });
  assert.equal(result.text, 'Advisory only.'); assert.equal(f.calls.length, 2);
});

test('absolute deadline, explicit cancellation, default-disabled and prompt boundary', async t => {
  const f = await fixture(t, () => {});
  f.config.policy.timeoutMs = 150;
  const start = Date.now();
  await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env }), /cancelled_or_deadline/);
  assert.ok(Date.now() - start < 2000);
  const controller = new AbortController();
  const pending = complete(f.state, { ...f.config, policy: { maxAttempts: 3, timeoutMs: 2000 } }, 'research', { prompt: 'risk' }, { env, signal: controller.signal });
  setTimeout(() => controller.abort(), 50);
  await assert.rejects(pending, /cancelled_or_deadline/);
  const before = f.calls.length;
  await assert.rejects(complete(f.state, { ...f.config, enabled: false }, 'research', { prompt: 'risk' }, { env }), /gateway_disabled/);
  for (const input of [{ prompt: 'x'.repeat(65537) }, { prompt: 'risk', tools: [] }, { prompt: '' }]) await assert.rejects(complete(f.state, f.config, 'research', input, { env }), /invalid_prompt/);
  assert.equal(f.calls.length, before);
});

test('completion deadline also bounds the first SQLite lock before provider dispatch', async t => {
  const f = await fixture(t);
  f.config.policy.timeoutMs = 150;
  let release, entered;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  const held = f.state.tx(async () => { entered(); await gate; });
  await started;
  try {
    const start = Date.now();
    await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env }), /cancelled_or_deadline/);
    assert.ok(Date.now() - start < 2000);
    assert.equal(f.calls.length, 0);
  } finally { release(); await held; }
});

test('HTTP-200 stream error/SDK stopReason is rejected without returning partial text or replay', async t => {
  const f = await fixture(t, (_, res) => sse(res, [
    { id: 'test', choices: [{ index: 0, delta: { content: 'partial must not escape' }, finish_reason: null }] },
    { error: { message: 'test-secret-a', code: 'failed' } },
  ]));
  await assert.rejects(complete(f.state, f.config, 'research', { prompt: 'risk' }, { env }), /provider_rejected/);
  assert.equal(f.calls.length, 1);
});

test('catalog sync preserves names, caps, custom rows, credentials and connection endpoint', async () => {
  const model = catalog.getModels('openai')[0];
  const config = validate({ schema: 1, enabled: true, connections: [{ id: 'primary', provider: 'openai', auth: { type: 'oauth' } }], presets: [{ id: 'mine', connection: 'primary', model: model.id, name: 'Do not rename', maxTokens: 10, temperature: 0.7 }] });
  const next = syncPresets(config, 'primary');
  assert.equal(next.presets.find(p => p.id === 'mine').name, 'Do not rename');
  assert.equal(next.presets.find(p => p.id === 'mine').maxTokens, 10);
  assert.equal(next.presets.find(p => p.id === 'mine').temperature, 0.7);
  assert.deepEqual(next.connections, config.connections);
  assert.deepEqual(syncPresets(next, 'primary'), next);
  assert.equal(mergePresets({ ...config, enabled: false }, config).enabled, false);
  const conflict = structuredClone(config); conflict.connections[0].provider = 'anthropic';
  assert.throws(() => mergePresets(config, conflict), /connection_conflict/);
  const custom = configuration('https://example.invalid/v1');
  custom.connections[0].provider = 'openai';
  const synced = syncPresets(custom, 'local');
  assert.deepEqual(synced.presets[0], custom.presets[0]); assert.deepEqual(synced.connections, custom.connections);
});

test('credential store exact post-write contract, rollback, namespace isolation, corruption, delete serialization', async t => {
  const f = await fixture(t);
  const c = { id: 'one', provider: 'openai' }, store = f.state.credentials(c);
  const original = { type: 'oauth', access: 'dummy-access', refresh: 'dummy-refresh', expires: 0 };
  assert.equal(await store.read('openai'), undefined);
  assert.deepEqual(await store.modify('openai', async () => original), original);
  assert.deepEqual(await store.modify('openai', async () => undefined), original);
  await assert.rejects(store.modify('openai', async () => { throw new Error('rollback'); }), /rollback/);
  assert.deepEqual(await store.read('openai'), original);
  assert.deepEqual(await store.list(), [{ providerId: 'openai', type: 'oauth' }]);
  assert.equal(await f.state.credentials({ id: 'two', provider: 'openai' }).read('openai'), undefined);
  let release; const gate = new Promise(r => { release = r; });
  let entered; const started = new Promise(r => { entered = r; });
  const modifying = store.modify('openai', async old => { entered(); await gate; return { ...old, access: 'new' }; });
  await started;
  const deleting = store.delete('openai');
  await sleep(30); release(); await modifying; await deleting;
  assert.equal(await store.read('openai'), undefined);
  await f.state.tx(db => db.prepare('INSERT INTO credentials VALUES (?, ?)').run(JSON.stringify([c.id, c.provider]), Buffer.from('bad')));
  await assert.rejects(store.read('openai'), /corrupt_credentials/);
});

test('cross-process ACTUAL SDK OAuth refresh occurs once under SQLite transaction', async t => {
  const f = await fixture(t);
  const store = f.state.credentials({ id: 'account', provider: 'test' });
  await store.modify('test', async () => ({ type: 'oauth', access: 'expired', refresh: 'dummy-refresh', expires: 0, refreshCount: 0 }));
  const results = await Promise.all([run([worker, f.home]), run([worker, f.home])]);
  for (const r of results) assert.equal(r.code, 0, r.stderr);
  assert.equal((await store.read('test')).refreshCount, 1);
});

test('process death rolls back and releases SQLite refresh lock', async t => {
  const f = await fixture(t);
  const store = f.state.credentials({ id: 'account', provider: 'test' });
  const original = { type: 'oauth', access: 'original', refresh: 'dummy-refresh', expires: 0 };
  await store.modify('test', async () => original);
  const child = spawn(process.execPath, [worker, f.home, 'hold'], { stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(() => { child.kill('SIGKILL'); });
  await new Promise((resolvePromise, reject) => {
    child.stdout.on('data', b => { if (b.toString().includes('locked')) resolvePromise(); });
    child.on('error', reject); child.on('exit', () => reject(new Error('worker exited before lock')));
  });
  child.kill('SIGKILL'); await once(child, 'exit');
  assert.deepEqual(await store.read('test'), original);
});

test('OAuth missing/failing credential never falls back to ambient API key', async t => {
  const f = await fixture(t);
  for (const providerId of ['openai', 'anthropic']) {
    const ambient = providerId === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY';
    const previous = process.env[ambient]; process.env[ambient] = 'ambient-must-not-charge';
    t.after(() => { if (previous === undefined) delete process.env[ambient]; else process.env[ambient] = previous; });
    const c = { id: `oauth-${providerId}`, provider: providerId, auth: { type: 'oauth' } };
    const model = catalog.getModels(providerId)[0];
    const config = validate({ schema: 1, enabled: true, connections: [c], presets: [{ id: 'oauth', connection: c.id, model: model.id }] });
    for (const overrides of [{ baseURL: 'https://attacker.invalid' }, { protocol: 'openai-completions', baseURL: 'https://attacker.invalid' }]) {
      assert.throws(() => validate({ ...config, connections: [{ ...c, ...overrides }] }));
    }
    const models = oauthModels(f.state, c);
    assert.equal(await models.getAuth(providerId), undefined);
    await assert.rejects(complete(f.state, config, 'oauth', { prompt: 'risk' }), /login_required/);
    await f.state.credentials(c).modify(providerId, async () => ({ type: 'oauth', access: 'expired', refresh: 'invalid', expires: 0 }));
    const provider = models.getProvider(providerId);
    let refreshes = 0;
    models.setProvider({ ...provider, auth: { oauth: { ...provider.auth.oauth, refresh: async () => { refreshes++; throw new Error('refresh failed'); } } } });
    await assert.rejects(models.getAuth(providerId), e => e.code === 'oauth');
    assert.equal(refreshes, 1);
    assert.equal((await f.state.credentials(c).read(providerId)).access, 'expired');
  }
  assert.equal(f.calls.length, 0);
});

test('real CLI import/show/status/export/complete/errors; malformed import preserves config and credentials', async t => {
  const f = await fixture(t);
  const file = join(f.home, 'import.json'); await writeFile(file, JSON.stringify(f.config));
  let r = await run([cli, 'config', 'import', file], { home: f.home }); assert.equal(r.code, 0, r.stderr);
  r = await run([cli, 'complete', 'research'], { home: f.home, input: JSON.stringify({ prompt: 'risk' }) });
  assert.equal(r.code, 0, r.stderr); assert.equal(JSON.parse(r.stdout).text, 'Advisory only.');
  for (const args of [['status'], ['config', 'show'], ['presets', 'export']]) {
    r = await run([cli, ...args], { home: f.home }); assert.equal(r.code, 0, r.stderr);
    assert.ok(!r.stdout.includes('test-secret')); assert.ok(!r.stderr.includes('test-secret'));
  }
  r = await run([cli, 'presets', 'export'], { home: f.home }); assert.equal(JSON.parse(r.stdout).enabled, false);
  const exportFile = join(f.home, 'portable.json');
  r = await run([cli, 'presets', 'export', exportFile], { home: f.home }); assert.equal(r.code, 0, r.stderr);
  assert.ok(!(await readFile(exportFile, 'utf8')).includes('test-secret'));
  r = await run([cli, 'presets', 'export', exportFile], { home: f.home }); assert.equal(r.code, 1);
  const store = f.state.credentials({ id: 'preserved', provider: 'openai' });
  await store.modify('openai', async () => ({ type: 'oauth', access: 'not-exported-access', refresh: 'not-exported-refresh', expires: 123 }));
  await writeFile(file, JSON.stringify({ ...f.config, inline_key: 'test-secret-a' }));
  r = await run([cli, 'config', 'import', file], { home: f.home }); assert.equal(r.code, 1); assert.ok(!r.stderr.includes('test-secret'));
  assert.deepEqual(await f.state.config(), f.config); assert.equal((await store.read('openai')).access, 'not-exported-access');
  r = await run([cli, 'complete', 'research'], { home: f.home, input: '{"prompt":"risk","tools":[]}' });
  assert.equal(r.code, 1); assert.match(r.stderr, /invalid_prompt/);
});

test('real CLI stdin is deadline-bounded and cancellable before provider dispatch', async t => {
  const f = await fixture(t);
  f.config.policy.timeoutMs = 150;
  await f.state.saveConfig(f.config);
  const child = spawn(process.execPath, [cli, 'complete', 'research'], { env: { ...process.env, GYM_MODEL_HOME: f.home, GYM_MODEL_ALLOW_LOOPBACK_HTTP: '1', ...env }, stdio: ['pipe', 'pipe', 'pipe'] });
  let stderr = ''; child.stderr.on('data', b => { stderr += b; });
  const [code] = await once(child, 'close');
  assert.equal(code, 1); assert.match(stderr, /cancelled_or_deadline/); assert.equal(f.calls.length, 0);
});

test('Windows real DPAPI store roundtrip, encrypted SQLite bytes and corrupt-ciphertext refusal', { skip: process.platform !== 'win32' }, async t => {
  const f = await fixture(t);
  const old = process.env.GYM_MODEL_PYTHON;
  process.env.GYM_MODEL_PYTHON ||= 'python';
  t.after(() => { if (old === undefined) delete process.env.GYM_MODEL_PYTHON; else process.env.GYM_MODEL_PYTHON = old; });
  const state = await new State(f.home).init();
  const c = { id: 'dpapi-test', provider: 'openai' }, store = state.credentials(c);
  const value = { type: 'oauth', access: 'dpapi-test-access', refresh: 'dpapi-test-refresh', expires: 12345 };
  await store.modify(c.provider, async () => value);
  assert.deepEqual(await store.read(c.provider), value);
  const file = await readFile(join(f.home, 'state.sqlite'));
  assert.ok(!file.includes(Buffer.from(value.access)) && !file.includes(Buffer.from(value.refresh)));
  await state.tx(db => db.prepare('UPDATE credentials SET value=? WHERE namespace=?').run(Buffer.from('corrupt'), JSON.stringify([c.id, c.provider])));
  await assert.rejects(store.read(c.provider), /corrupt_credentials/);
});

test('symlink or Windows junction state directories are rejected', async t => {
  const f = await fixture(t);
  const target = join(f.home, 'target'), link = join(f.home, 'link');
  await mkdir(target, { mode: 0o700 });
  await symlink(target, link, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(new State(link, identity).init(), /unsafe_state_path/);
});

test('state rejects symlinked config and POSIX broad permissions', async t => {
  const f = await fixture(t);
  const target = join(f.home, 'other.json'); await writeFile(target, JSON.stringify(emptyConfig()), { mode: 0o600 });
  try { await symlink(target, join(f.home, 'config.json')); }
  catch (e) { if (process.platform === 'win32' && e.code === 'EPERM') { t.skip('Windows symlink privilege unavailable'); return; } throw e; }
  await assert.rejects(f.state.config(), /unsafe_state_path/);
  if (process.platform !== 'win32') { await rm(join(f.home, 'config.json')); await chmod(f.home, 0o755); await assert.rejects(new State(f.home, identity).init(), /unsafe_state_permissions/); await chmod(f.home, 0o700); }
});
