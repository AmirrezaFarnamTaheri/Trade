import { builtinModels } from '@earendil-works/pi-ai/providers/all';
import { createHash } from 'node:crypto';

export const catalog = builtinModels({ authContext: { env: async () => undefined, fileExists: async () => false } });
export const MAX_CONFIG = 1024 * 1024;
export class GatewayError extends Error {
  constructor(code) { super(code); this.code = code; }
}
export function check(value, code = 'invalid_config') { if (!value) throw new GatewayError(code); }
export function exact(obj, keys) {
  check(obj && typeof obj === 'object' && !Array.isArray(obj));
  check(Object.keys(obj).every(k => keys.includes(k)));
}
function text(v, max = 200) { return typeof v === 'string' && v.length > 0 && v.length <= max && !/[\x00-\x1f\x7f]/.test(v); }
function id(v) { return typeof v === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$/.test(v); }
function integer(v, min, max) { return Number.isInteger(v) && v >= min && v <= max; }
export function endpoint(value, allowLoopback = false) {
  check(text(value, 2048));
  let u; try { u = new URL(value); } catch { throw new GatewayError('invalid_config'); }
  check(!u.username && !u.password && !value.includes('?') && !value.includes('#') && !value.split('/')[2]?.includes('@'));
  check(u.protocol === 'https:' || (allowLoopback && u.protocol === 'http:' && ['127.0.0.1', '[::1]', 'localhost'].includes(u.hostname)));
  return u.href.replace(/\/$/, '');
}
export function validate(input, { allowLoopback = false } = {}) {
  exact(input, ['schema', 'enabled', 'connections', 'presets', 'policy']);
  check(input.schema === 1 && (input.enabled === undefined || typeof input.enabled === 'boolean'));
  check(Array.isArray(input.connections) && input.connections.length <= 100);
  check(Array.isArray(input.presets) && input.presets.length <= 5000);
  const result = structuredClone(input);
  result.enabled ??= false;
  result.policy ??= {};
  exact(result.policy, ['maxAttempts', 'timeoutMs']);
  result.policy.maxAttempts ??= 3;
  result.policy.timeoutMs ??= 30000;
  check(integer(result.policy.maxAttempts, 1, 3) && integer(result.policy.timeoutMs, 100, 120000));
  const connections = new Map();
  for (const c of result.connections) {
    exact(c, ['id', 'provider', 'protocol', 'baseURL', 'auth']);
    check(id(c.id) && id(c.provider) && !connections.has(c.id));
    check((c.protocol === undefined && c.baseURL === undefined) || (typeof c.protocol === 'string' && c.protocol.length > 0 && typeof c.baseURL === 'string'));
    if (c.protocol) {
      check(['openai-completions', 'openai-responses', 'anthropic-messages'].includes(c.protocol));
      c.baseURL = endpoint(c.baseURL, allowLoopback);
    } else check(!!catalog.getProvider(c.provider));
    exact(c.auth, ['type', 'env']);
    if (c.auth.type === 'api_key') {
      check(Array.isArray(c.auth.env) && c.auth.env.length >= 1 && c.auth.env.length <= 100);
      check(c.auth.env.every(n => typeof n === 'string' && /^[A-Z_][A-Z0-9_]{0,127}$/.test(n)) && new Set(c.auth.env).size === c.auth.env.length);
      check(!!c.protocol || !!catalog.getProvider(c.provider)?.auth.apiKey);
    } else {
      check(c.auth.type === 'oauth' && Object.keys(c.auth).length === 1 && !c.protocol && !!catalog.getProvider(c.provider)?.auth.oauth);
    }
    connections.set(c.id, c);
  }
  const ids = new Set();
  for (const p of result.presets) {
    exact(p, ['id', 'name', 'connection', 'model', 'maxTokens', 'temperature', 'catalog']);
    check(id(p.id) && !ids.has(p.id) && connections.has(p.connection) && text(p.model));
    ids.add(p.id);
    check(p.name === undefined || text(p.name));
    const c = connections.get(p.connection);
    const known = catalog.getModel(c.provider, p.model);
    check(c.protocol || known, 'unknown_model');
    check(p.maxTokens === undefined || integer(p.maxTokens, 1, Math.min(65536, known?.maxTokens ?? 65536)));
    check(p.temperature === undefined || (Number.isFinite(p.temperature) && p.temperature >= 0 && p.temperature <= ((c.protocol ?? known?.api) === 'anthropic-messages' ? 1 : 2)));
    if (p.catalog !== undefined) {
      exact(p.catalog, ['name', 'api', 'contextWindow', 'maxTokens', 'reasoning']);
      check(text(p.catalog.name) && text(p.catalog.api) && integer(p.catalog.contextWindow, 1, 10000000) && integer(p.catalog.maxTokens, 1, 1000000) && typeof p.catalog.reasoning === 'boolean');
    }
  }
  check(Buffer.byteLength(JSON.stringify(result)) <= MAX_CONFIG);
  return result;
}
export const emptyConfig = () => ({ schema: 1, enabled: false, connections: [], presets: [], policy: { maxAttempts: 3, timeoutMs: 30000 } });
export function parseConfig(bytes, options) {
  check(bytes.length <= MAX_CONFIG, 'config_too_large');
  let parsed; try { parsed = JSON.parse(bytes.toString('utf8')); } catch { throw new GatewayError('invalid_config'); }
  return validate(parsed, options);
}
export function metadata(m) { return { name: m.name, api: m.api, contextWindow: m.contextWindow, maxTokens: m.maxTokens, reasoning: m.reasoning }; }
export function syncPresets(config, connectionId, options) {
  const next = structuredClone(config);
  const c = next.connections.find(c => c.id === connectionId);
  check(c, 'unknown_connection');
  for (const m of catalog.getModels(c.provider)) {
    const rows = next.presets.filter(p => p.connection === c.id && p.model === m.id);
    if (rows.length) { for (const p of rows) p.catalog = metadata(m); }
    else {
      const hash = createHash('sha256').update(JSON.stringify([c.id, c.provider, m.id])).digest('hex').slice(0, 24);
      next.presets.push({ id: `catalog-${hash}`, connection: c.id, model: m.id, catalog: metadata(m) });
    }
  }
  return validate(next, options);
}
export function mergePresets(current, incoming, options) {
  const next = structuredClone(current);
  for (const c of incoming.connections) {
    const old = next.connections.find(x => x.id === c.id);
    check(!old || JSON.stringify(old) === JSON.stringify(c), 'connection_conflict');
    if (!old) next.connections.push(c);
  }
  for (const p of incoming.presets) {
    const i = next.presets.findIndex(x => x.id === p.id);
    if (i < 0) next.presets.push(p);
    else { check(next.presets[i].connection === p.connection && next.presets[i].model === p.model, 'preset_conflict'); next.presets[i] = p; }
  }
  return validate(next, options);
}
