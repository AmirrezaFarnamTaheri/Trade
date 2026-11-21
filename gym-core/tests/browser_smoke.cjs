'use strict';
// Real-browser smoke test (Edge on Windows, Chrome/Chromium elsewhere). Node 22 built-ins and an isolated synthetic store.
// GYM_PYTHON and GYM_BROWSER override the interpreter and browser executables.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');

const core = path.resolve(__dirname, '..');
const windows = process.platform === 'win32';
const python = process.env.GYM_PYTHON || path.join(core, '.venv', windows ? 'Scripts' : 'bin', windows ? 'python.exe' : 'python');
const browserPath = [process.env.GYM_BROWSER,
  path.join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(candidate => candidate && fs.existsSync(candidate));
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'tradinggym-ui-'));
const artifacts = path.resolve(process.env.GYM_SCREENSHOT_DIR || path.join(core, '..', '.pi', 'ui-verification'));
const errors = [];
let browser, server, socket;
let diagnostic = async () => ({});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function until(check, label, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try { const result = await check(); if (result) return result; } catch {}
    await pause(100);
  }
  throw new Error(`Timed out: ${label}`);
}

function launch(executable, args) {
  // Own process group off Windows, so stop() also ends the browser's helper processes.
  const child = spawn(executable, args, { cwd: core, windowsHide: true, detached: !windows, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stdout.on('data', data => { child.output = (child.output || '').slice(-4000) + data; });
  child.on('error', error => errors.push(error.message));
  child.stderr.on('data', data => { child.lastError = (child.lastError || '').slice(-1000) + data.toString().slice(-1000); });
  return child;
}

function stop(child) {
  if (!child?.pid || child.exitCode !== null) return;
  if (windows) spawnSync('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore', timeout: 10000 });
  else try { process.kill(-child.pid, 'SIGKILL'); } catch {}
}

(async () => {
  assert(browserPath, 'Edge, Chrome or Chromium is required (or set GYM_BROWSER)');
  assert(fs.existsSync(python), 'gym-core .venv is required');
  fs.mkdirSync(artifacts, { recursive: true });
  const seeded = spawnSync(python, ['-m', 'gym.cli', '--data', temporary, 'demo-seed', '--hours', '4'], { cwd: core, encoding: 'utf8', timeout: 60000, windowsHide: true });
  assert.equal(seeded.status, 0, seeded.stderr || 'synthetic seeding failed');
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  server = launch(python, ['-m', 'gym.cli', '--data', temporary, 'run', '--demo', '--port', String(port), '--no-browser']);
  // The session key lives only in the printed link's fragment; without it every write is refused.
  const link = await until(() => new RegExp(`${origin}/#t=[\\w-]+`).exec(server.output || '')?.[0], 'demo server link');
  await until(async () => (await fetch(origin)).ok, 'demo server');
  const profile = path.join(temporary, 'edge-profile');
  // Containers and Ubuntu 24.04 runners block Chrome's user-namespace sandbox; this test page is local and trusted.
  browser = launch(browserPath, [...(windows ? [] : ['--no-sandbox']), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  const debugging = await until(() => fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split(/\r?\n/)[0], 'browser CDP');
  const page = await (await fetch(`http://127.0.0.1:${debugging}/json/new?about:blank`, { method: 'PUT' })).json();
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
    const call = pending.get(message.id);
    if (call) { pending.delete(message.id); clearTimeout(call.timer); message.error ? call.reject(new Error(message.error.message)) : call.resolve(message.result); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 30000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  diagnostic = async () => ({ errors, page: await evaluate(`({
    title:document.title, hash:location.hash, ready:document.readyState,
    focus:{id:document.activeElement?.id,html:document.activeElement?.outerHTML.slice(0,1000),
      visible:document.activeElement?.matches(':focus-visible'),documentFocused:document.hasFocus(),
      outlineStyle:getComputedStyle(document.activeElement).outlineStyle},
    formValid:document.querySelector('#compare-form')?.checkValidity(),
    button:document.querySelector('#compare-submit')?.outerHTML,
    fieldsDisabled:document.querySelector('#comparison-fields')?.disabled,
    values:[...document.querySelectorAll('#compare-form input,#compare-form select')].map(n=>({id:n.id,value:n.value})),
    result:document.querySelector('#compare-result')?.textContent.slice(0,3000),
    requests:performance.getEntriesByType('resource').filter(n=>n.name.includes('/api/compare')).map(n=>({url:n.name,duration:n.duration})),
    intercepted:!!window.__comparison
  })`) });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: link });
  await until(() => evaluate('document.querySelectorAll("#market-rows tr[data-symbol]").length > 0 || document.querySelector("#market-rows")?.textContent.includes("BTC")'), 'real market rows');
  const routes = await evaluate('[...document.querySelectorAll("nav [data-view]")].map(node => node.dataset.view)');
  assert.equal(routes.length, 9);
  // Accessibility: with axe-core available (CI installs it; AXE_PATH or a resolvable package), every view
  // is checked against WCAG 2 A/AA. Critical violations fail; serious ones are reported.
  let axeSource = null;
  try { axeSource = fs.readFileSync(process.env.AXE_PATH || require.resolve('axe-core/axe.min.js'), 'utf8'); } catch {}
  const accessibility = {};
  for (const route of routes) {
    await evaluate(`document.querySelector('nav [data-view="${route}"]').click()`);
    await until(() => evaluate(`document.querySelector('#v-${route}')?.hidden === false`), `navigation ${route}`);
    if (axeSource) {
      await pause(800);
      if (!await evaluate('typeof axe === "object"')) await evaluate(axeSource + '; true');
      accessibility[route] = await evaluate(`axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'] }).then(result =>
        result.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help,
          details: v.nodes.slice(0, 5).map(n => ({ target: n.target, failure: n.failureSummary })) })))`);
    }
  }
  const critical = Object.entries(accessibility).flatMap(([route, found]) => found.filter(v => v.impact === 'critical').map(v => `${route}: ${v.id} (${v.nodes}) ${v.help}`));
  assert.equal(await evaluate("performance.getEntriesByType('resource').some(({name}) => name.includes('/operator-timeline.mjs'))"), false,
    'evidence module stays off the startup path');
  await evaluate(`(() => {
    document.querySelector('nav [data-view="health"]').click();
    document.querySelector('#operator-timeline-source').value = 'feed-quality';
    document.querySelector('#operator-timeline-form').requestSubmit();
  })()`);
  await until(() => evaluate(`performance.getEntriesByType('resource').some(({name}) =>
    name.includes('/api/timeline?') && new URL(name).searchParams.get('source') === 'feed-quality')
    && document.querySelector('#operator-timeline-results').textContent.trim()
    && !document.querySelector('#operator-timeline-form button').disabled
    && !document.querySelector('#operator-timeline-results').textContent.includes(t('requestError'))`),
  'filtered evidence timeline');
  assert.equal(await evaluate(`performance.getEntriesByType('resource').filter(({name}) => {
    const url = new URL(name);
    return url.pathname === '/operator-timeline.mjs' && /^[a-f0-9]{16}$/.test(url.searchParams.get('v'));
  }).length`), 1, 'versioned evidence module loads on demand');
  for (const [route, found] of Object.entries(accessibility))
    for (const v of found.filter(v => v.impact === 'serious')) console.log(`a11y serious · ${route}: ${v.id} (${v.nodes}) ${v.help}`);
  assert.deepEqual(critical, [], 'critical accessibility violations');
  await evaluate('document.querySelector("nav [data-view=markets]").click()');
  await evaluate('document.fonts.ready.then(() => true)');
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'desktop horizontal overflow');
  const screenshots = [];
  async function screenshot(name) {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(path.join(artifacts, name), Buffer.from(shot.data, 'base64'));
    screenshots.push(name);
  }
  await screenshot('markets-desktop.png');
  await evaluate(`(() => {
    const original = window.fetch.bind(window);
    window.__restoreFxFetch = () => { window.fetch = original; };
    window.fetch = (url, init) => String(url).includes('/api/fx-route?')
      ? Promise.resolve(Response.json({
        direction: 'TMN_TO_USDT', fee_per_leg: '0.001', depth_scope: 'TOP_OF_BOOK_ONLY', max_quote_age_seconds: 120,
        routes: [{route: 'BTCTMN > BTCUSDT', legs: 2, received: '100.500000', capacity: '10000000',
          fits_displayed_size: true, leg_details: [{symbol: 'BTCTMN', side: 'BUY', bid: '9000000', ask: '9001000',
            displayed_base_quantity: '2', spread_bps: '1.11', quote_at: '2026-11-21T10:00:00.000000Z'}]}],
        direct_available: true,
        direct_route: {route: 'USDTTMN', legs: 1, received: '100.000000'},
        saving_vs_direct_bps: 50,
        order_submitted: false
      })) : original(url, init);
    document.querySelector('#fx-route-form').closest('details').open = true;
    document.querySelector('#fx-route-submit').click();
  })()`);
  await until(() => evaluate(`(() => {
    const text = document.querySelector('#fx-route-output').textContent;
    return text.includes('BTCTMN > BTCUSDT') && text.includes('100') && text.includes('50')
      && text.includes('2026-11-21T10:00:00.000000Z') && text.includes('120');
  })()`), 'successful FX route, direct proceeds and quote evidence');
  await evaluate("window.__restoreFxFetch(); document.querySelector('#fx-route-form').closest('details').open = false");
  async function openMarketDepth() {
    await until(() => evaluate(`document.querySelector('[data-market="BTCUSDT"]')`), 'BTCUSDT row');
    await evaluate(`(() => {
      const button = document.querySelector('[data-market="BTCUSDT"]');
      if (button.getAttribute('aria-expanded') !== 'true') { button.focus(); button.click(); }
    })()`);
    await until(() => evaluate('document.querySelectorAll(".depth-track").length === 6'), 'observed demo book depth');
    assert(await evaluate(`(() => {
      const cells = [...document.querySelectorAll('.depth-row [role=cell]')];
      const band = state.markets.markets.find(row => row.symbol === 'BTCUSDT').liquidity.bands[0];
      return cells[0].textContent === digits(band.bid_base) &&
        Math.max(...cells.map(cell => Number(cell.querySelector('rect + rect').getAttribute('width')))) === 100;
    })()`), 'depth displays exact amounts and shares one scale');
    assert(await evaluate(`(() => {
      const chart = document.querySelector('.depth-figure');
      chart.scrollIntoView({block:'center', inline:'nearest'});
      const {left, right} = chart.getBoundingClientRect();
      return left >= -1 && right <= innerWidth + 1;
    })()`), 'depth chart fits without sideways scrolling');
  }
  await openMarketDepth();
  assert.equal(await evaluate('document.activeElement?.dataset.market'), 'BTCUSDT', 'pair keeps keyboard focus');
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('market-depth-desktop-en.png');
  await evaluate(`(() => {
    const market = state.markets.markets.find(row => row.symbol === 'BTCUSDT');
    window.__restoreDepth = () => { market.liquidity = original; renderMarkets(); };
    const original = market.liquidity;
    market.liquidity = {status: 'UNAVAILABLE', bands: []};
    renderMarkets();
  })()`);
  assert(await evaluate(`document.querySelector('.depth-section').textContent.includes('No usable order book depth') &&
    !document.querySelector('.depth-track')`), 'missing depth shows a message, not a zero bar');
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('market-depth-unavailable.png');
  await evaluate('window.__restoreDepth(); delete window.__restoreDepth');
  await evaluate(`(() => { const select = document.querySelector('#market-sort');
    select.value = 'spread'; select.dispatchEvent(new Event('change', {bubbles:true}));
    document.querySelector('[data-market="BTCUSDT"]').click(); window.scrollTo(0, 0);
  })()`);
  if (process.env.GYM_SCREENSHOTS === '1') {
    for (const route of routes) {
      await evaluate(`document.querySelector('nav [data-view="${route}"]').click()`);
      await evaluate('refresh()');
      await screenshot(`desktop-${route}.png`);
    }
  }
  await evaluate('document.querySelector("nav [data-view=research]").click()');
  await evaluate(`(() => {
    const form = document.querySelector("#run-filter-form");
    form.elements.symbol.value = "btcusdt";
    form.elements.strategy.value = "ema-trend";
    form.elements.date_from.value = "2026-11-01";
    form.elements.fee_rate.value = "0.001";
    form.elements.evidence_stage.value = "UNKNOWN";
    form.requestSubmit();
  })()`);
  await until(() => evaluate(`performance.getEntriesByType('resource').some(({name}) => {
    if (!name.includes('/api/runs?')) return false;
    const {searchParams: q} = new URL(name);
    return q.get('symbol') === 'BTCUSDT' && q.get('strategy') === 'ema-trend'
      && q.get('date_from') === '2026-11-01' && q.get('fee_rate') === '0.001'
      && q.get('evidence_stage') === 'UNKNOWN' && q.get('offset') === '0';
  })`), 'saved run filters submit to the real catalog endpoint');
  await evaluate(`(() => {
    const form = document.querySelector("#run-filter-form");
    form.reset();
    form.requestSubmit();
  })()`);
  await evaluate('document.querySelector("#tab-compare").click()');
  await until(() => evaluate('!document.querySelector("#comparison-fields").disabled'), 'research catalog');
  await evaluate(`(() => {
    document.querySelector('#compare-symbol').value = 'BTCUSDT';
    document.querySelector('#compare-symbol').dispatchEvent(new Event('change', {bubbles:true}));
    for (const [id, value] of [['candidate-first','ema-trend'],['candidate-second','sma-reversion']]) {
      const node = document.getElementById(id); node.value = value; node.dispatchEvent(new Event('change', {bubbles:true}));
    }
    document.querySelector('#compare-resolution').value = '1min';
    document.querySelector('#compare-fee').value = '0.001';
    const original = window.fetch.bind(window);
    window.fetch = async (...args) => { const response = await original(...args);
      if (String(args[0]).includes('/api/compare')) { window.__comparisonStatus = response.status; window.__comparison = await response.clone().json(); }
      return response;
    };
    return true;
  })()`);
  await until(() => evaluate('document.querySelector("#compare-from").value && document.querySelector("#compare-to").value'), 'paired UTC window');
  await until(() => evaluate('!document.querySelector("#comparison-fields").disabled && !document.querySelector("#compare-submit").matches(":disabled")'), 'symbol coverage refresh completed');
  assert(await evaluate('document.querySelector("#compare-form").checkValidity()'), 'research form validity');
  await evaluate('document.querySelector("#compare-submit").click()');
  const comparison = await until(() => evaluate('window.__comparison || null'), 'real paired comparison', 60000);
  assert.equal(await evaluate('window.__comparisonStatus'), 200, JSON.stringify(comparison));
  assert.equal(comparison.mode, 'COMPARE');
  assert.equal(comparison.runs.length, 2);
  assert.equal(comparison.runs[0].inputs.data, comparison.runs[1].inputs.data);
  assert.equal(comparison.runs[0].inputs.snapshots, comparison.runs[1].inputs.snapshots);
  await until(() => evaluate('document.querySelector("#compare-result").textContent.includes("ema-trend")'), 'rendered paper result');
  await screenshot('research-desktop.png');
  await evaluate(`location.hash = '#research/runs/${comparison.runs[0].run_id}'`);
  const benchmark = await until(() => evaluate(`(() => {
    const chart = document.querySelector('#run-detail .run-benchmark');
    if (state.record?.run_id !== '${comparison.runs[0].run_id}' || !chart) return null;
    return {
      zeros: [...chart.querySelectorAll('li svg line')].map(line => line.getAttribute('x1')),
      cash: chart.querySelector('li:last-child bdi')?.textContent,
    };
  })()`), 'saved demo run benchmark');
  assert.deepEqual(benchmark.zeros, ['50', '50']);
  assert.equal(Number(benchmark.cash), 0);
  assert.ok(await evaluate(`(() => {
    const placed = '2026-11-21T10:00:00.000000Z';
    const receipt = {ref: 'BTCUSDT#1', maker: true, placed_at: placed, status: 'FILLED', queue_ahead: '3',
      limit_prints_considered: 2, suspected_identical_prints: 1, identical_print_capacity_qty: '0.2', qty: '0.5'};
    renderRun({...state.record, result: {...state.record.result, orders: [receipt,
      {ref: 'BTCUSDT#1.1', parent: 'BTCUSDT#1', placed_at: placed, status: 'CANCELLED', remaining_qty: '0.8'}]}});
    const timeline = document.querySelector('[data-key="maker-timeline"]');
    const passed = timeline.querySelectorAll('tbody tr').length === 2
      && timeline.textContent.includes('BTCUSDT#1 → BTCUSDT#1.1')
      && timeline.textContent.includes('0.2') && timeline.textContent.includes(t('unknown'));
    const filter = timeline.querySelector('[data-maker-status]');
    filter.value = 'CANCELLED';
    filter.dispatchEvent(new Event('change', {bubbles: true}));
    const filtered = document.querySelectorAll('[data-key="maker-timeline"] tbody tr');
    const matched = filtered.length === 1 && filtered[0].textContent.includes('BTCUSDT#1.1');
    renderRun(state.record);
    return passed && matched;
  })()`), 'maker timeline retains partial, duplicate and unknown evidence');
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('run-benchmark-desktop-en.png');
  await evaluate(`(() => {
    const summary = document.querySelector('[data-key="run-benchmarks"] summary');
    summary.focus(); summary.click(); renderRun(state.record);
  })()`);
  assert.ok(await evaluate('document.querySelector("[data-key=run-benchmarks]").open && document.activeElement.dataset.focus === "run-benchmarks"'));
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('run-benchmark-details-en.png');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate(`document.querySelector('#language-toggle').click();
    if (document.documentElement.dataset.theme !== 'dark') document.querySelector('#theme-toggle').click();
    document.querySelector('[data-key="run-benchmarks"]').open = false;
    document.querySelector('.run-benchmark').closest('section').scrollIntoView();`);
  assert.ok(await evaluate(`document.documentElement.dir === 'rtl' && document.documentElement.scrollWidth <= innerWidth + 1 &&
    document.querySelector('[data-key="run-benchmarks"] summary').getBoundingClientRect().height >= 44`));
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('run-benchmark-mobile-fa-dark.png');
  assert.ok(await evaluate(`(() => {
    renderRun({ ...state.record, baselines: {} });
    document.querySelector('[data-key="run-benchmarks"]').closest('section').scrollIntoView();
    return !document.querySelector('.run-benchmark') && document.querySelector('#run-detail').textContent.includes(t('baselineMissing'));
  })()`));
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('run-benchmark-unavailable-fa.png');
  await send('Emulation.clearDeviceMetricsOverride');
  await evaluate(`document.querySelector('#language-toggle').click(); document.querySelector('#theme-toggle').click();
    document.querySelector('#tab-compare').click();`);
  await send('Page.reload');
  await until(() => evaluate('document.querySelector("#compare-fee")?.value === "0.001" && !document.querySelector("#comparison-fields")?.disabled'), 'persisted research inputs');
  const theme = await evaluate('document.documentElement.dataset.theme');
  await evaluate('document.querySelector("#theme-toggle").click()');
  assert.notEqual(await evaluate('document.documentElement.dataset.theme'), theme);
  await evaluate('document.querySelector("#language-toggle").click()');
  assert.equal(await evaluate('document.documentElement.dir'), 'rtl');
  assert.equal(await evaluate('document.documentElement.lang'), 'fa');
  await evaluate('document.querySelector("nav [data-view=markets]").click()');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'mobile RTL horizontal overflow');
  await screenshot('markets-mobile-fa.png');
  assert.equal(await evaluate('document.querySelector("#market-sort").value'), 'spread', 'market sort survives reload');
  await openMarketDepth();
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('market-depth-mobile-fa-dark.png');
  await evaluate('document.querySelector("#language-toggle").click()');
  await evaluate('document.querySelector("#theme-toggle").click()');
  await openMarketDepth();
  if (process.env.GYM_SCREENSHOTS === '1') await screenshot('market-depth-mobile-en-light.png');
  await evaluate(`document.querySelector('[data-market="BTCUSDT"]').click(); window.scrollTo(0, 0);`);
  assert.equal(await evaluate('document.documentElement.dir'), 'ltr');
  await screenshot('markets-mobile-en.png');
  const mobileTargets = [];
  for (const width of [375, 600]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 844, deviceScaleFactor: 1, mobile: true });
    for (const selectedTheme of ['light', 'dark']) {
      if (await evaluate('document.documentElement.dataset.theme') !== selectedTheme)
        await evaluate('document.querySelector("#theme-toggle").click()');
      for (const language of ['en', 'fa']) {
        if (await evaluate('document.documentElement.lang') !== language)
          await evaluate('document.querySelector("#language-toggle").click()');
        for (const route of routes) {
          await evaluate(`document.querySelector('nav [data-view="${route}"]').click()`);
          await until(() => evaluate(`document.querySelector('#v-${route}')?.hidden === false`), `mobile navigation ${route}`);
          const geometry = await evaluate(`(() => {
            const controls = [...document.querySelectorAll('.button, .segmented button, .tabs [role="tab"], .symbol-button')]
              .filter(node => node.getClientRects().length)
              .map(node => ({ id: node.id || node.textContent.trim(), height: node.getBoundingClientRect().height }));
            return { overflow: document.documentElement.scrollWidth > innerWidth + 1, controls };
          })()`);
          assert.equal(geometry.overflow, false, `${width}px ${language} ${selectedTheme} ${route}: horizontal overflow`);
          assert(geometry.controls.length > 0, `${route}: no visible action controls checked`);
          assert.deepEqual(geometry.controls.filter(control => control.height < 43.99), [],
            `${width}px ${language} ${selectedTheme} ${route}: action, tab and market-selection targets below 44px`);
          if (process.env.GYM_SCREENSHOTS === '1' && route === 'overview') {
            await evaluate('refresh()');
            await screenshot(`overview-${width}-${language}-${selectedTheme}.png`);
          }
          mobileTargets.push({ width, language, theme: selectedTheme, route,
            controls: geometry.controls.length, minimumHeight: Math.min(...geometry.controls.map(control => control.height)) });
        }
      }
    }
  }
  if (await evaluate('document.documentElement.lang') !== 'en')
    await evaluate('document.querySelector("#language-toggle").click()');
  await send('Page.bringToFront');
  await evaluate('document.querySelector("#theme-toggle").focus()');
  assert(await evaluate('document.hasFocus() && document.activeElement?.id === "theme-toggle"'), 'keyboard focus start');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  const keyboardFocus = (await diagnostic()).page.focus;
  console.log('Keyboard focus:', JSON.stringify(keyboardFocus));
  assert.equal(keyboardFocus.id, 'zone-toggle', 'Tab advances from theme to zone control');
  assert(keyboardFocus.documentFocused && keyboardFocus.visible && keyboardFocus.outlineStyle !== 'none', 'keyboard focus outline');
  // Destructive rule actions open a labelled dialog: Cancel has focus, cancelling sends nothing and refocuses the trigger.
  await evaluate('document.querySelector("nav [data-view=rules]").click()');
  await until(() => evaluate('document.querySelector("#v-rules")?.hidden === false'), 'rules view');
  await evaluate(`(() => { window.__posts = 0; const original = window.fetch; window.fetch = (url, init) => { if ((init?.method || "GET") === "POST") window.__posts += 1; return original(url, init); }; return true; })()`);
  await evaluate('document.querySelector("#load-preset").click()');
  await until(() => evaluate('document.querySelector("dialog.confirm-dialog")?.open === true'), 'confirmation dialog');
  assert(await evaluate('document.activeElement?.value === "cancel" && document.querySelector("dialog.confirm-dialog").getAttribute("aria-labelledby") === "confirm-dialog-text"'), 'dialog focus and label');
  await evaluate('document.activeElement.click()');
  await until(() => evaluate('!document.querySelector("dialog.confirm-dialog") && document.activeElement?.id === "load-preset"'), 'dialog closed and focus returned');
  assert.equal(await evaluate('window.__posts'), 0, 'cancelled preset must not POST');
  // A failing source is named in the banner, and the banner clears once the source answers again.
  await evaluate(`(() => { const original = window.fetch; window.__restoreFetch = () => { window.fetch = original; };
    window.fetch = (url, init) => String(url).includes('/api/markets') ? Promise.reject(new TypeError('offline')) : original(url, init); return true; })()`);
  await evaluate('document.querySelector("nav [data-view=overview]").click()');
  await until(() => evaluate('!document.querySelector("#connection-error").hidden && document.querySelector("#connection-error-detail").textContent.includes("markets")'), 'named failing source');
  await evaluate('window.__restoreFetch(); document.querySelector("#retry").click()');
  await until(() => evaluate('document.querySelector("#connection-error").hidden'), 'banner clears after recovery');
  await until(() => evaluate('document.querySelectorAll("#overview-answer .trial-counts li").length === 4 && document.querySelectorAll("#overview-answer .answer-trials tbody tr").length >= 9'), 'outcome chart and trial register');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'overview does not overflow');
  await evaluate(`(() => {
    const original = window.fetch;
    window.__restoreFetch = () => { window.fetch = original; };
    window.fetch = (url, init) => String(url).includes('/api/evidence') ? Promise.reject(new TypeError('offline')) : original(url, init);
    const summary = document.querySelector('#overview-answer summary');
    summary.focus();
    summary.click();
  })()`);
  await evaluate('refresh()');
  assert.ok(await evaluate(`document.querySelector('#overview-answer').textContent.includes('Showing evidence last loaded at')`));
  assert.ok(await evaluate(`document.querySelector('#overview-answer details').open && document.activeElement.matches('#overview-answer summary')`));
  await evaluate('window.__restoreFetch(); document.querySelector("#retry").click()');
  await until(() => evaluate(`!document.querySelector('#overview-answer').textContent.includes('Showing evidence last loaded at')`), 'evidence freshness recovers');
  assert.ok(await evaluate('document.querySelector("#overview-answer details").open'));
  await evaluate(`(() => {
    const filter = document.querySelector('#trial-verdict-filter');
    filter.focus();
    filter.value = 'OPEN';
    filter.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  assert.ok(await evaluate(`(() => {
    const rows = [...document.querySelectorAll('.answer-trials tbody tr')];
    return rows.length > 0 && rows.every(row => row.cells[2].textContent === 'Not run') && document.activeElement.id === 'trial-verdict-filter';
  })()`), 'filter shows only open trials and keeps focus');
  await evaluate('refresh()');
  assert.equal(await evaluate('document.querySelector("#trial-verdict-filter").value'), 'OPEN');
  await evaluate(`(() => {
    const filter = document.querySelector('#trial-verdict-filter');
    filter.value = '';
    filter.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  assert.ok(await evaluate(`document.querySelectorAll('.answer-trials tbody tr').length >= 9`), 'all verdicts restores the register');
  await screenshot('overview-answer.png');
  // Persian desktop view of the densest tables, for a human RTL review; layout must hold without overflow.
  await evaluate('document.querySelector("#language-toggle").click()');
  await until(() => evaluate('document.documentElement.lang === "fa" && document.documentElement.dir === "rtl"'), 'Persian overview');
  await evaluate('document.querySelector("#overview-answer details").open = true');
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Persian overview does not overflow');
  await screenshot('overview-answer-fa.png');
  await evaluate('document.querySelector("#language-toggle").click(); refresh()');
  await evaluate(`(() => {
    const prior = state.evidence, original = window.fetch;
    const fixture = { ...prior, forward: {
      symbol: 'BTCUSDT', net: '-12.50', hold_net: '8.25', days: 4, missing_days: 0,
      withheld: 0, trades: 2, fees: '0.25', latest: '2026-11-18T12:00:00Z'
    } };
    window.fetch = (url, init) => String(url) === '/api/evidence'
      ? Promise.resolve(Response.json(fixture)) : original(url, init);
    window.__restoreEvidence = () => { window.fetch = original; };
  })()`);
  await until(() => evaluate('document.querySelectorAll(".forward-comparison li").length === 3'), 'synthetic forward comparison');
  assert.deepEqual(await evaluate(`[...document.querySelectorAll('.forward-comparison li')].map(row => [row.querySelector('bdi').textContent, Number(row.querySelector('rect:nth-child(2)').getAttribute('x'))])`), [['-12.50', 0], ['0', 50], ['8.25', 50]], 'benchmark compares losses, cash and gains on one scale');
  if (process.env.GYM_SCREENSHOTS === '1') {
    await evaluate('document.querySelector(".answer-trials").open = false; document.querySelector(".trial-forward").scrollIntoView()');
    await screenshot('overview-forward-demo.png');
  }
  await evaluate('window.__restoreEvidence()');
  assert.deepEqual(errors, [], 'browser exceptions');
  const report = { mode: 'DEMO', routes, comparison_id: comparison.comparison_id,
    accessibility: axeSource ? accessibility : 'axe-core not installed', mobileTargets, keyboardFocus, screenshots,
    checks: [`${routes.length} real views`, 'real paired replay and result rendering', 'identical decision/data windows', 'persisted form inputs', 'theme switch', 'EN/FA RTL switch', 'desktop/mobile overflow', '44px mobile action, tab and market-selection targets at 375px/600px in both languages and themes', 'keyboard focus', 'confirmation dialog cancel', 'named failing source and recovery', 'no JavaScript exceptions'] };
  fs.writeFileSync(path.join(artifacts, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`PASS: real browser UI (${path.basename(browserPath)}); screenshots/report: ${artifacts}`);
})().catch(async error => {
  fs.mkdirSync(artifacts, { recursive: true });
  try { fs.writeFileSync(path.join(artifacts, 'browser-failure.json'), JSON.stringify(await diagnostic(), null, 2)); } catch {}
  console.error(error.stack || error.message); if (server?.lastError) console.error(server.lastError); process.exitCode = 1;
}).finally(() => {
  socket?.close();
  stop(browser);
  stop(server);
  try { fs.rmSync(temporary, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 }); } catch {}
});
