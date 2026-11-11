/* Model settings use the gateway API; secrets never enter browser storage or URLs. */
window.gymModels = (() => {
  let context, language, status, login, poll;
  const $ = id => document.getElementById(id);
  const words = Object.fromEntries(['en', 'fa'].map(l => [l, Object.fromEntries(["add", "advanced", "auth", "calls", "cancel", "choose", "clear", "code", "config", "configured", "connected", "connections", "cost", "disconnected", "enabled", "export", "failed", "help", "id", "import", "key", "keyHelp", "keys", "link", "noUsage", "none", "oauth", "oauthAccept", "oauthWarn", "pending", "plaintext", "preset", "prompt", "provider", "refresh", "reply", "result", "saved", "send", "signIn", "signOut", "storage", "sync", "title", "tokensIn", "tokensOut", "unavailable", "unknownCost", "usage"].map(k => [k, T[l]['models' + k[0].toUpperCase() + k.slice(1)]]))]));
  const w = key => words[language][key];
  const esc = value => context.esc(String(value));
  const request = (action, value) => context.api('/api/models', { method: 'POST', body: JSON.stringify({ action, value }) }, 145000);
  const button = (action, id, text) => `<button type="button" class="button button-small" data-model-action="${action}" data-connection="${esc(id)}">${esc(text)}</button>`;
  async function act(fn) {
    $('models-message').textContent = '';
    try { await fn(); $('models-message').textContent = w('saved'); }
    catch { $('models-message').textContent = w('failed'); }
  }
  function renderStatus() {
    const storageLabels = { WINDOWS_USER_DPAPI: 'modelsStorageDpapi', PRIVATE_FILE_PASSPHRASE_SEALED: 'modelsStorageSealed',
      PRIVATE_FILE_PLAINTEXT: 'modelsPlaintext', CREDENTIAL_PROTECTION_UNAVAILABLE: 'modelsStorageUnavailable' };
    const protection = T[language][storageLabels[status.storage]] ?? status.storage;
    const legacy = status.legacy_plaintext_possible ?? status.storage === 'PRIVATE_FILE_PLAINTEXT';
    $('models-storage').textContent = `${w('storage')}: ${protection}${legacy ? ' ' + T[language].modelsStorageLegacy : ''}`;
    $('models-enabled').checked = status.enabled;
    $('models-connections').innerHTML = status.connections.length ? status.connections.map(c => `<article class="panel"><h3>${esc(c.id)} · ${esc(c.provider)}</h3><p>${esc(c.auth.type === 'oauth' ? w(c.loggedIn ? 'connected' : 'disconnected') : `${c.configuredKeys} ${w('configured')}`)}</p><div class="actions">${c.auth.type === 'oauth' ? button('login', c.id, w('signIn')) + button('logout', c.id, w('signOut')) : ''}${button('sync', c.id, w('sync'))}</div>${c.auth.type === 'api_key' && c.auth.stored ? `<form data-key-connection="${esc(c.id)}"><label>${esc(w('key'))}<input type="password" data-secret-keys autocomplete="off" autocapitalize="off" spellcheck="false" required dir="ltr"></label><p class="field-help">${esc(w('keyHelp'))}</p><div class="actions"><button class="button" type="submit">${esc(w('keys'))}</button>${button('clear', c.id, w('clear'))}</div></form>` : ''}</article>`).join('') : `<p>${esc(w('none'))}</p>`;
    const selected = $('models-preset').value;
    $('models-preset').innerHTML = status.presets.map(p => `<option value="${esc(p.id)}">${esc(p.connection)} / ${esc(p.name || p.model)}</option>`).join('');
    if (status.presets.some(p => p.id === selected)) $('models-preset').value = selected;
    $('models-send').disabled = !status.enabled || !status.presets.length;
  }
  async function reload() { status = await request('status'); renderStatus(); renderUsage(await request('usage').catch(() => null)); }
  function renderUsage(data) {
    const rows = data?.by_model || [];
    $('models-usage').innerHTML = rows.length ? `<div class="table-wrap" tabindex="0"><table class="data"><thead><tr>${['provider', 'preset', 'calls', 'tokensIn', 'tokensOut', 'cost'].map(k => `<th scope="col">${esc(w(k))}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.provider)}</td><td dir="ltr">${esc(r.model)}</td><td class="num">${esc(r.calls)}</td><td class="num">${esc(r.input_tokens ?? '—')}</td><td class="num">${esc(r.output_tokens ?? '—')}</td><td class="num" dir="ltr">${esc(r.cost)}${r.calls_without_cost ? ` <small>(${esc(r.calls_without_cost)} ${esc(w('unknownCost'))})</small>` : ''}</td></tr>`).join('')}</tbody></table></div><p class="field-help">${esc(data.note)}</p>` : `<p>${esc(w('noUsage'))}</p>`;
  }
  async function pollLogin() {
    clearTimeout(poll);
    if (!login) return;
    try {
      const value = await request('session', login);
      const target = $('models-login');
      if (value.state !== 'PENDING') { target.textContent = value.state; login = null; await reload(); return; }
      const promptId = value.prompt?.id || '';
      if (target.dataset.prompt !== promptId || target.dataset.links !== JSON.stringify(value.links)) {
        target.dataset.prompt = promptId; target.dataset.links = JSON.stringify(value.links);
        target.innerHTML = `<p>${esc(w('pending'))}${value.userCode ? ' · ' + esc(value.userCode) : ''}</p>${value.links.map(url => `<p><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(w('link'))}</a></p>`).join('')}${value.prompt ? `<form id="models-reply"><label>${esc(w(value.prompt.type === 'select' ? 'choose' : 'code'))}${value.prompt.type === 'select' ? `<select id="models-answer">${value.prompt.options.map(o => `<option value="${esc(o.id)}">${esc(o.label)}</option>`).join('')}</select>` : '<input id="models-answer" type="password" autocomplete="off" required dir="ltr">'}</label><button class="button" type="submit">${esc(w('reply'))}</button></form>` : ''}${button('cancel', '', w('cancel'))}`;
      }
      poll = setTimeout(pollLogin, 1000);
    } catch { $('models-login').textContent = w('failed'); login = null; }
  }
  async function mount(api, escape) {
    context = { api, esc: escape };
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next) return;
    language = next;
    $('models-content').innerHTML = `<p class="lead">${esc(w('help'))}</p><div class="actions"><button id="models-refresh" class="button" type="button">${esc(w('refresh'))}</button><label><input id="models-enabled" type="checkbox"> ${esc(w('enabled'))}</label></div><p id="models-storage" class="field-help"></p><p id="models-message" role="status"></p><section class="panel"><h2>${esc(w('add'))}</h2><form id="models-add"><div class="ticket-fields"><label>${esc(w('id'))}<input id="models-id" pattern="[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}" maxlength="100" required dir="ltr"></label><label>${esc(w('provider'))}<select id="models-provider"></select></label><label>${esc(w('auth'))}<select id="models-auth"></select></label></div><button class="button" type="submit">${esc(w('add'))}</button></form></section><h2>${esc(w('connections'))}</h2><div id="models-connections"></div><section id="models-login" class="panel" role="status" aria-live="polite"></section><section class="panel"><h2>${esc(w('prompt'))}</h2><form id="models-complete"><label>${esc(w('preset'))}<select id="models-preset"></select></label><label>${esc(w('prompt'))}<textarea id="models-prompt" maxlength="32000" required></textarea></label><button id="models-send" class="button" type="submit" disabled>${esc(w('send'))}</button></form><h3>${esc(w('result'))}</h3><pre id="models-result" class="output" dir="auto"></pre></section><section class="panel"><h2>${esc(w('usage'))}</h2><div id="models-usage"></div></section><details class="panel"><summary>${esc(w('advanced'))}</summary><label>${esc(w('config'))}<textarea id="models-config" rows="8" spellcheck="false" dir="ltr"></textarea></label><div class="actions"><button id="models-import" type="button" class="button">${esc(w('import'))}</button><button id="models-export" type="button" class="button">${esc(w('export'))}</button></div></details>`;
    $('models-refresh').onclick = () => act(reload);
    $('models-enabled').onchange = () => act(async () => { await request('enabled', $('models-enabled').checked); await reload(); });
    $('models-add').onsubmit = event => { event.preventDefault(); act(async () => {
      // Consumer-subscription OAuth is opt-in, behind the provider-terms warning.
      if ($('models-auth').value === 'oauth' && !await confirmAction(w('oauthWarn'), w('oauthAccept'), event.submitter)) return;
      await request('connection', { id: $('models-id').value, provider: $('models-provider').value,
        auth: $('models-auth').value === 'oauth' ? { type: 'oauth' } : { type: 'api_key', env: [], stored: true } });
      $('models-id').value = ''; await reload();
    }); };
    $('models-connections').onsubmit = event => { event.preventDefault(); const form = event.target;
      if (!form.dataset.keyConnection) return;
      const input = form.querySelector('[data-secret-keys]'); const keys = input.value.split(/\r?\n/).map(k => k.trim()).filter(Boolean); input.value = '';
      act(async () => { await request('keys', { connection: form.dataset.keyConnection, keys }); await reload(); });
    };
    $('models-content').onclick = event => {
      const target = event.target.closest('[data-model-action]'); if (!target) return;
      act(async () => {
        const action = target.dataset.modelAction, connection = target.dataset.connection;
        if (action === 'clear') await request('keys', { connection, keys: [] });
        else if (action === 'cancel') { await request('cancel', { id: login }); }
        else if (action === 'login') { const result = await request('login', connection); login = result.id; $('models-login').dataset.prompt = 'new'; await pollLogin(); }
        else await request(action, connection);
        await reload();
      });
    };
    $('models-login').onsubmit = event => { event.preventDefault(); act(async () => {
      const input = $('models-answer'), answer = input.value; input.value = '';
      await request('reply', { id: login, prompt: $('models-login').dataset.prompt, answer }); await pollLogin();
    }); };
    $('models-complete').onsubmit = event => { event.preventDefault(); act(async () => {
      $('models-send').disabled = true;
      try { $('models-result').textContent = JSON.stringify(await request('complete', { preset: $('models-preset').value, prompt: $('models-prompt').value }), null, 2); }
      finally { renderStatus(); renderUsage(await request('usage').catch(() => null)); }
    }); };
    $('models-import').onclick = () => act(async () => { await request('import', JSON.parse($('models-config').value)); await reload(); });
    $('models-export').onclick = () => {
      const config = { schema: status.schema, enabled: false, policy: status.policy, presets: status.presets,
        connections: status.connections.map(({ configuredKeys, loggedIn, ...c }) => c) };
      const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = 'model-connections.json'; a.click(); URL.revokeObjectURL(url);
    };
    try {
      const providers = (await request('providers')).filter(p => p.completionSupported);
      $('models-provider').innerHTML = providers.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
      if (providers.some(p => p.id === 'openai')) $('models-provider').value = 'openai';
      const authOptions = () => { const p = providers.find(p => p.id === $('models-provider').value); $('models-auth').innerHTML = (p.api_key ? `<option value="api_key">${esc(w('key'))}</option>` : '') + (p.oauth ? `<option value="oauth">${esc(w('oauth'))}</option>` : ''); };
      $('models-provider').onchange = authOptions; authOptions(); await reload();
    } catch { $('models-message').textContent = w('unavailable'); language = undefined; }
  }
  return { mount };
})();
