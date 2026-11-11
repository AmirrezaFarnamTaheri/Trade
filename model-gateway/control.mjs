import { randomUUID } from 'node:crypto';
import { catalog, check, exact, GatewayError, metadata, mergePresets, syncPresets, validate } from './config.mjs';
import { complete, oauthModels, providerList } from './runtime.mjs';

// Interactive state stays in this trusted process; only opaque session IDs reach the browser.
export class ModelControl {
  constructor(state) { this.state = state; this.sessions = new Map(); }
  close() { for (const session of this.sessions.values()) session.controller.abort(); }
  async request(input) {
    exact(input, ['action', 'value']);
    const { action, value } = input;
    if (action === 'providers') return providerList();
    if (action === 'catalog') {
      check(typeof value === 'string' && catalog.getProvider(value), 'unknown_provider');
      return catalog.getModels(value).map(m => ({ id: m.id, ...metadata(m) }));
    }
    const config = await this.state.config();
    if (action === 'status') {
      const connections = [];
      for (const c of config.connections) {
        const keys = c.auth.type === 'api_key' && c.auth.stored ? await this.state.apiKeys(c) : [];
        connections.push({ ...c, configuredKeys: c.auth.type === 'api_key' ? new Set([...keys,
          ...c.auth.env.map(n => process.env[n]).filter(v => typeof v === 'string' && v.trim())]).size : 0,
        loggedIn: c.auth.type === 'oauth' && (await this.state.credentials(c).list()).length > 0 });
      }
      return { ...config, connections, mode: 'RESEARCH_ONLY', funded_authority: false,
        ...this.state.protection() };
    }
    if (action === 'session') {
      check(typeof value === 'string' && this.sessions.has(value), 'unknown_login');
      return this.sessions.get(value).view;
    }
    if (action === 'reply' || action === 'cancel') {
      exact(value, action === 'reply' ? ['id', 'prompt', 'answer'] : ['id']);
      const session = this.sessions.get(value.id);
      check(session, 'unknown_login');
      if (action === 'cancel') session.controller.abort();
      else {
        check(session.reply && value.prompt === session.view.prompt?.id, 'login_not_waiting');
        check(typeof value.answer === 'string' && value.answer.length > 0 && value.answer.length <= 8192 && !/[\x00\r\n]/.test(value.answer), 'invalid_login_reply');
        if (session.view.prompt.type === 'select') check(session.view.prompt.options.some(o => o.id === value.answer), 'invalid_selection');
        session.reply(value.answer);
      }
      return { accepted: true };
    }
    if (action === 'complete') {
      exact(value, ['preset', 'prompt']);
      return complete(this.state, config, value.preset, { prompt: value.prompt });
    }
    check(![...this.sessions.values()].some(s => s.view.state === 'PENDING'), 'login_in_progress');
    if (action === 'import') {
      await this.state.saveConfig(mergePresets(config, validate(value, this.state.options), this.state.options));
      return { saved: true };
    }
    if (action === 'enabled') {
      check(typeof value === 'boolean');
      await this.state.saveConfig({ ...config, enabled: value });
      return { enabled: value };
    }
    if (action === 'connection') {
      // Existing IDs are immutable; changing their provider would silently re-scope credentials.
      check(!config.connections.some(c => c.id === value?.id), 'connection_exists');
      await this.state.saveConfig({ ...config, connections: [...config.connections, value] });
      return { saved: true };
    }
    const id = typeof value === 'string' ? value : value?.connection;
    const c = config.connections.find(c => c.id === id);
    check(c, 'unknown_connection');
    if (action === 'sync') {
      await this.state.saveConfig(syncPresets(config, c.id, this.state.options));
      return { synced: true };
    }
    if (action === 'keys') {
      exact(value, ['connection', 'keys']);
      check(Array.isArray(value.keys), 'invalid_api_keys');
      await this.state.apiKeys(c, value.keys);
      return { configuredKeys: value.keys.length };
    }
    if (action === 'logout') {
      check(c.auth.type === 'oauth', 'oauth_unavailable');
      await this.state.credentials(c).delete(c.provider);
      return { loggedIn: false };
    }
    if (action === 'login') return this.login(c);
    throw new GatewayError('unknown_action');
  }
  async login(connection) {
    check(connection.auth.type === 'oauth', 'oauth_unavailable');
    for (const [id, s] of this.sessions) if (s.view.state !== 'PENDING') this.sessions.delete(id);
    const id = randomUUID(), controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(600000)]);
    const session = { controller, view: { id, connection: connection.id, state: 'PENDING', prompt: null, links: [] } };
    this.sessions.set(id, session);
    const safeURL = text => {
      const u = new URL(text);
      check(u.protocol === 'https:' && !u.username && !u.password && text.length <= 8192, 'unsafe_login_url');
      return u.href;
    };
    const deviceId = await this.state.deviceId();
    session.task = Promise.resolve().then(() => oauthModels(this.state, connection).login(connection.provider, 'oauth', {
      signal,
      prompt: prompt => {
        check(['select', 'text'].includes(prompt.type), 'unsupported_login_prompt');
        const promptSignal = prompt.signal ? AbortSignal.any([signal, prompt.signal]) : signal;
        return new Promise((resolve, reject) => {
          const abort = () => { session.reply = undefined; session.view.prompt = null; reject(new GatewayError('login_cancelled')); };
          promptSignal.throwIfAborted();
          session.view.prompt = { id: randomUUID(), type: prompt.type,
            options: prompt.type === 'select' ? prompt.options.map(o => ({ id: o.id, label: o.label })) : [] };
          session.reply = answer => { promptSignal.removeEventListener('abort', abort); session.reply = undefined; session.view.prompt = null; resolve(answer); };
          promptSignal.addEventListener('abort', abort, { once: true });
        });
      },
      notify: event => {
        if (event.type === 'auth_url') session.view.links = [safeURL(event.url)];
        if (event.type === 'device_code') {
          session.view.links = [safeURL(event.verificationUri)];
          session.view.userCode = event.userCode;
        }
        if (event.type === 'info' && event.links?.length) session.view.links = event.links.slice(0, 5).map(l => safeURL(l.url));
      },
    }, { agentName: 'TradingGYM advisory gateway', getDeviceId: () => deviceId }))
      .then(() => { session.view.state = 'CONNECTED'; })
      .catch(() => { session.view.state = signal.aborted ? 'CANCELLED' : 'FAILED'; })
      .finally(() => { session.reply = undefined; session.view.prompt = null; session.view.links = []; delete session.view.userCode; });
    return { id, state: 'PENDING' };
  }
}
