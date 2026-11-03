import { createModels, createProvider, cleanupSessionResources } from '@earendil-works/pi-ai';
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy';
import { openAIResponsesApi } from '@earendil-works/pi-ai/api/openai-responses.lazy';
import { anthropicMessagesApi } from '@earendil-works/pi-ai/api/anthropic-messages.lazy';
import { createHash, randomUUID } from 'node:crypto';
import { setTimeout as sleep } from 'node:timers/promises';
import { catalog, check, GatewayError } from './config.mjs';

const apis = { 'openai-completions': openAICompletionsApi, 'openai-responses': openAIResponsesApi, 'anthropic-messages': anthropicMessagesApi };
const supported = new Set([...Object.keys(apis), 'openai-codex-responses']);
export const providerList = () => catalog.getProviders().map(p => ({ id: p.id, name: p.name, api_key: !!p.auth.apiKey, oauth: !!p.auth.oauth, completionSupported: p.getModels().some(m => supported.has(m.api)) }));
const noAmbientAuth = { env: async () => undefined, fileExists: async () => false };
export function oauthModels(state, c) {
  const provider = catalog.getProvider(c.provider);
  check(provider?.auth.oauth && c.auth.type === 'oauth', 'oauth_unavailable');
  const models = createModels({ credentials: state.credentials(c), authContext: noAmbientAuth });
  models.setProvider({ ...provider, auth: { oauth: provider.auth.oauth } });
  return models;
}
function requestModel(c, p) {
  const known = catalog.getModel(c.provider, p.model);
  const model = known ? { ...known } : {
    id: p.model, name: p.model, provider: c.provider, api: c.protocol,
    baseUrl: c.baseURL, reasoning: false, input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 65536,
  };
  if (c.protocol) { model.api = c.protocol; model.baseUrl = c.baseURL; delete model.headers; }
  check(supported.has(model.api), 'unsupported_protocol');
  check(p.maxTokens === undefined || p.maxTokens <= model.maxTokens, 'unsupported_output_limit');
  return model;
}
function cooldown(headers, now) {
  const delays = [];
  for (const key of ['retry-after-ms', 'retry-after', 'ratelimit-reset', 'x-ratelimit-reset-requests', 'x-ratelimit-reset-tokens']) {
    const value = headers.get(key);
    if (value === null) continue;
    let ms;
    if (key === 'retry-after-ms') ms = Number(value);
    else if (key === 'retry-after') ms = Number.isFinite(Number(value)) ? Number(value) * 1000 : Date.parse(value) - now;
    else if (/^[0-9.]+$/.test(value)) {
      const n = Number(value); ms = n > 1e12 ? n - now : n > 1e9 ? n * 1000 - now : n * 1000;
    } else {
      const parts = [...value.matchAll(/([0-9.]+)(ms|s|m|h)/g)];
      if (parts.length && parts.map(p => p[0]).join('') === value) ms = parts.reduce((sum, p) => sum + Number(p[1]) * ({ ms: 1, s: 1000, m: 60000, h: 3600000 }[p[2]]), 0);
    }
    if (Number.isFinite(ms) && ms >= 0) delays.push(ms);
  }
  return delays.length ? Math.max(...delays) : 60000;
}
async function boundedBody(response, max) {
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader();
  const parts = []; let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.length;
      check(size <= max, 'response_too_large'); parts.push(value);
    }
    return Buffer.concat(parts);
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
function failure(info) {
  if (!info) return 'transient';
  if (info.status === 401 || ['invalid_api_key', 'invalid_token', 'authentication_error'].includes(info.code)) return 'auth';
  if (info.status === 429 || (info.status === 403 && ['insufficient_quota', 'quota_exceeded', 'billing_hard_limit_reached', 'usage_limit_reached', 'rate_limit_exceeded'].includes(info.code))) return 'cooldown';
  if (info.status >= 500) return 'transient';
  return 'fatal';
}
function abortable(promise, signal) {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => reject(new GatewayError('cancelled_or_deadline'));
    signal.addEventListener('abort', abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}
export async function complete(state, config, presetId, input, { signal: external, env = process.env } = {}) {
  check(config.enabled === true, 'gateway_disabled');
  check(input && typeof input === 'object' && !Array.isArray(input) && Object.keys(input).length === 1 && typeof input.prompt === 'string' && input.prompt.length > 0 && Buffer.byteLength(input.prompt) <= 65536, 'invalid_prompt');
  const p = config.presets.find(p => p.id === presetId);
  check(p, 'unknown_preset');
  const c = config.connections.find(c => c.id === p.connection);
  const model = requestModel(c, p);
  const timer = AbortSignal.timeout(config.policy.timeoutMs);
  const signal = external ? AbortSignal.any([timer, external]) : timer;
  const options = { signal };
  const sessionId = randomUUID();
  const context = { messages: [{ role: 'user', content: input.prompt, timestamp: Date.now() }] };
  const scope = createHash('sha256').update(JSON.stringify([c.id, c.provider, model.id, model.api, model.baseUrl])).digest('hex');
  let keys = [], fingerprints = [], models;
  try {
    if (c.auth.type === 'api_key') {
      keys = [...new Set(c.auth.env.map(n => env[n]).filter(v => typeof v === 'string' && v.trim().length > 0))];
      check(keys.every(k => Buffer.byteLength(k) <= 16384 && !/[\r\n\x00]/.test(k)), 'invalid_environment_key');
      fingerprints = await state.fingerprints(keys, options);
      await state.pool(scope, fingerprints, () => {}, options);
      check(keys.length, 'no_environment_keys');
    } else {
      check(await state.credentials(c).read(c.provider, options), 'login_required');
      models = oauthModels(state, c);
    }
    for (let attempt = 0; attempt < config.policy.maxAttempts; attempt++) {
      signal.throwIfAborted();
      let fp, key;
      if (c.auth.type === 'api_key') {
        const i = await state.pool(scope, fingerprints, pool => {
          for (let n = 0; n < fingerprints.length; n++) {
            const i = (pool.cursor + n) % fingerprints.length;
            const h = pool.health[fingerprints[i]];
            if (!h.invalid && h.until <= Date.now()) { pool.cursor = (i + 1) % fingerprints.length; return i; }
          }
          return -1;
        }, options);
        check(i >= 0, 'pool_exhausted');
        key = keys[i]; fp = fingerprints[i];
        const provider = c.protocol ? createProvider({ id: c.provider, baseUrl: c.baseURL, models: [model], auth: { apiKey: { name: 'Environment key', resolve: async () => ({ auth: { apiKey: key } }) } }, api: apis[c.protocol]() }) : {
          ...catalog.getProvider(c.provider), auth: { apiKey: { name: 'Environment key', resolve: async () => ({ auth: { apiKey: key } }) } },
        };
        models = createModels({ authContext: noAmbientAuth }); models.setProvider(provider);
      }
      let info, sent = false, responseError = false;
      const guardedFetch = async (url, init) => {
        check(!sent && !signal.aborted, 'request_budget_exceeded'); sent = true;
        const response = await fetch(url, { ...init, redirect: 'error', signal: init?.signal ? AbortSignal.any([signal, init.signal]) : signal });
        if (!response.ok) {
          info = { status: response.status, wait: cooldown(response.headers, Date.now()) };
          try {
            const error = JSON.parse((await boundedBody(response, 16384)).toString('utf8'));
            info.code = typeof error.error?.code === 'string' ? error.error.code : error.error?.type;
          } catch { /* Provider error bodies are untrusted; status still determines policy. */ }
          return new Response(JSON.stringify({ error: { message: 'Provider rejected request', type: 'provider_error' } }), { status: response.status, headers: { 'content-type': 'application/json' } });
        }
        info = { status: response.status };
        let count = 0;
        const body = response.body?.pipeThrough(new TransformStream({ transform(chunk, controller) { count += chunk.length; if (count > 2 * 1024 * 1024) { responseError = true; controller.error(new GatewayError('response_too_large')); } else controller.enqueue(chunk); } }));
        return new Response(body, { status: response.status, headers: response.headers });
      };
      let result;
      try {
        result = await abortable(models.complete(model, context, {
          signal, fetch: guardedFetch, maxRetries: 0, timeoutMs: config.policy.timeoutMs,
          transport: 'sse', sessionId, maxTokens: p.maxTokens ?? Math.min(1024, model.maxTokens),
          ...(p.temperature === undefined ? {} : { temperature: p.temperature }),
        }), signal);
      } catch { if (signal.aborted) throw new GatewayError('cancelled_or_deadline'); }
      if (signal.aborted || result?.stopReason === 'aborted') throw new GatewayError('cancelled_or_deadline');
      if (result && !['error', 'aborted'].includes(result.stopReason) && !result.errorMessage && !responseError) {
        check(result.stopReason !== 'toolUse' && result.content.every(b => b.type !== 'toolCall'), 'unexpected_tool_call');
        const text = result.content.filter(b => b.type === 'text').map(b => b.text).join('');
        check(Buffer.byteLength(text) <= 1024 * 1024, 'response_too_large');
        return { mode: 'RESEARCH_ONLY', funded_authority: false, text, usage: result.usage, model: { provider: c.provider, id: model.id, preset: p.id, connection: c.id }, stopReason: result.stopReason };
      }
      const kind = !sent || responseError || (info?.status >= 200 && info?.status < 400) ? 'fatal' : failure(info);
      if (c.auth.type === 'api_key' && (kind === 'auth' || kind === 'cooldown')) {
        await state.pool(scope, fingerprints, pool => { const h = pool.health[fp]; h.invalid = kind === 'auth'; h.until = kind === 'cooldown' ? Date.now() + info.wait : 0; }, options);
      }
      if (kind === 'fatal') throw new GatewayError('provider_rejected');
      if (c.auth.type === 'oauth' && kind === 'auth') throw new GatewayError('oauth_failed');
      if (c.auth.type === 'oauth' && kind === 'cooldown') throw new GatewayError('provider_cooling');
      if (attempt + 1 === config.policy.maxAttempts) throw new GatewayError('attempts_exhausted');
      if (kind === 'transient') await sleep(100 * 2 ** attempt, undefined, options);
    }
    throw new GatewayError('attempts_exhausted');
  } catch (error) {
    if (signal.aborted) throw new GatewayError('cancelled_or_deadline');
    if (error instanceof GatewayError) throw error;
    throw new GatewayError('gateway_request_failed');
  } finally { cleanupSessionResources(sessionId); }
}
