#!/usr/bin/env node
import { createInterface } from 'node:readline/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { State, boundedRead, atomicWrite } from './state.mjs';
import { catalog, metadata, parseConfig, mergePresets, syncPresets, check, GatewayError, MAX_CONFIG } from './config.mjs';
import { complete, providerList, oauthModels } from './runtime.mjs';

async function stdinJSON(signal) {
  const chunks = []; let bytes = 0;
  const abort = () => process.stdin.destroy(new GatewayError('cancelled_or_deadline'));
  signal.throwIfAborted();
  signal.addEventListener('abort', abort, { once: true });
  try {
    for await (const chunk of process.stdin) {
      bytes += chunk.length; check(bytes <= 70 * 1024, 'input_too_large'); chunks.push(chunk);
    }
    try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { throw new GatewayError('invalid_prompt'); }
  } finally { signal.removeEventListener('abort', abort); }
}
async function login(state, config, id, device, signal) {
  const c = config.connections.find(c => c.id === id);
  check(c, 'unknown_connection');
  check(c.auth.type === 'oauth', 'oauth_unavailable');
  check(!device || c.provider === 'openai-codex', 'device_flow_unavailable');
  check(process.stdin.isTTY || device, 'login_requires_tty');
  const models = oauthModels(state, c);
  const deviceId = await state.deviceId();
  const rl = createInterface({ input: process.stdin, output: process.stderr });
  const loginSignal = AbortSignal.any([signal, AbortSignal.timeout(600000)]);
  try {
    await models.login(c.provider, 'oauth', {
      signal: loginSignal,
      prompt: async prompt => {
        const s = prompt.signal ? AbortSignal.any([loginSignal, prompt.signal]) : loginSignal;
        if (device && prompt.type === 'select') {
          check(prompt.options.some(o => o.id === 'device_code'), 'device_flow_unavailable'); return 'device_code';
        }
        check(process.stdin.isTTY && prompt.type !== 'secret', 'unsupported_login_prompt');
        if (prompt.type === 'select') {
          process.stderr.write(prompt.options.map((o, i) => `${i + 1}. ${o.label}`).join('\n') + '\n');
          const answer = await rl.question(`${prompt.message}: `, { signal: s });
          const choice = Number(answer);
          check(Number.isInteger(choice) && choice > 0 && choice <= prompt.options.length, 'invalid_selection');
          return prompt.options[choice - 1].id;
        }
        return rl.question(`${prompt.message}: `, { signal: s });
      },
      notify: event => {
        if (event.type === 'auth_url') process.stderr.write(`Open in your browser: ${event.url}\n`);
        else if (event.type === 'device_code') process.stderr.write(`Open ${event.verificationUri}\nEnter device code: ${event.userCode}\n`);
        else if (event.type === 'info') {
          process.stderr.write('Provider sign-in information:\n');
          for (const link of event.links || []) process.stderr.write(`${link.url}\n`);
        } else process.stderr.write('Authenticating…\n');
      },
    }, { agentName: 'TradingGYM advisory gateway', getDeviceId: () => deviceId });
    return { connection: id, loggedIn: true };
  } finally { rl.close(); }
}
export async function main(args = process.argv.slice(2)) {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  process.once('SIGINT', cancel); process.once('SIGTERM', cancel);
  try {
    if (args.length === 1 && args[0] === 'providers') return providerList();
    if (args.length === 2 && args[0] === 'catalog') {
      check(catalog.getProvider(args[1]), 'unknown_provider');
      return catalog.getModels(args[1]).map(m => ({ id: m.id, provider: m.provider, ...metadata(m) }));
    }
    const state = await new State(undefined, { allowLoopback: process.env.GYM_MODEL_ALLOW_LOOPBACK_HTTP === '1' }).init();
    if (args.length === 3 && args[0] === 'config' && args[1] === 'import') {
      const config = parseConfig(await boundedRead(resolve(args[2]), MAX_CONFIG), state.options);
      await state.saveConfig(config);
      return { imported: true, enabled: config.enabled };
    }
    const config = await state.config();
    if (args.length === 2 && args[0] === 'config' && args[1] === 'show') return config;
    if (args[0] === 'presets' && args[1] === 'export' && [2, 3].includes(args.length)) {
      const portable = { ...config, enabled: false };
      if (!args[2]) return portable;
      await atomicWrite(resolve(args[2]), JSON.stringify(portable, null, 2) + '\n', { exclusive: true });
      return { exported: true };
    }
    if (args.length === 3 && args[0] === 'presets' && args[1] === 'import') {
      const incoming = parseConfig(await boundedRead(resolve(args[2]), MAX_CONFIG), state.options);
      const next = mergePresets(config, incoming, state.options);
      await state.saveConfig(next); return { imported: true, presets: next.presets.length };
    }
    if (args.length === 3 && args[0] === 'presets' && args[1] === 'sync') {
      const next = syncPresets(config, args[2], state.options);
      await state.saveConfig(next); return { synced: true, presets: next.presets.length };
    }
    if ([2, 3].includes(args.length) && args[0] === 'login' && (args.length === 2 || args[2] === '--device')) return await login(state, config, args[1], args.length === 3, controller.signal);
    if (args.length === 2 && args[0] === 'logout') {
      const c = config.connections.find(c => c.id === args[1]); check(c, 'unknown_connection');
      await state.credentials(c).delete(c.provider, { signal: controller.signal });
      return { connection: c.id, loggedIn: false };
    }
    if (args.length === 1 && args[0] === 'status') {
      const connections = [];
      for (const c of config.connections) {
        const auth = c.auth.type === 'oauth' ? { type: 'oauth', loggedIn: (await state.credentials(c).list({ signal: controller.signal })).length > 0 }
          : { type: 'api_key', env: c.auth.env, configuredKeys: new Set([...(c.auth.stored ? await state.apiKeys(c) : []), ...c.auth.env.map(n => process.env[n]).filter(v => typeof v === 'string' && v.trim().length > 0)]).size };
        connections.push({ id: c.id, provider: c.provider, auth });
      }
      return { schema: 1, enabled: config.enabled, mode: 'RESEARCH_ONLY', funded_authority: false, connections, presets: config.presets.length };
    }
    if (args.length === 2 && args[0] === 'complete') {
      check(config.enabled, 'gateway_disabled');
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(config.policy.timeoutMs)]);
      return await complete(state, config, args[1], await stdinJSON(signal), { signal });
    }
    throw new GatewayError('usage: providers | catalog <provider> | config import <file> | config show | presets export [file] | presets import <file> | presets sync <connection> | login <connection> [--device] | logout <connection> | status | complete <preset>');
  } finally { process.removeListener('SIGINT', cancel); process.removeListener('SIGTERM', cancel); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().then(result => process.stdout.write(JSON.stringify(result) + '\n')).catch(error => {
    process.stderr.write(JSON.stringify({ error: error instanceof GatewayError ? error.code : 'gateway_failed' }) + '\n');
    process.exitCode = 1;
  });
}
