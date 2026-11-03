'use strict';
// Windows Edge smoke test. Uses only Node built-ins and an isolated synthetic store.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { spawn, spawnSync } = require('node:child_process');

const core = path.resolve(__dirname, '..');
const python = path.join(core, '.venv', 'Scripts', 'python.exe');
const edge = path.join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'tradinggym-ui-'));
const artifacts = path.resolve(core, '..', '.pi', 'ui-verification');
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
  const child = spawn(executable, args, { cwd: core, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  child.on('error', error => errors.push(error.message));
  child.stderr.on('data', data => { child.lastError = (child.lastError || '').slice(-1000) + data.toString().slice(-1000); });
  return child;
}

function stop(child) {
  if (child?.pid && child.exitCode === null) {
    spawnSync('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore', timeout: 10000 });
  }
}

(async () => {
  assert(fs.existsSync(edge), 'Windows Edge is required');
  assert(fs.existsSync(python), 'gym-core .venv is required');
  fs.mkdirSync(artifacts, { recursive: true });
  const seeded = spawnSync(python, ['-m', 'gym.cli', '--data', temporary, 'demo-seed', '--hours', '4'], { cwd: core, encoding: 'utf8', timeout: 60000, windowsHide: true });
  assert.equal(seeded.status, 0, seeded.stderr || 'synthetic seeding failed');
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  server = launch(python, ['-m', 'gym.cli', '--data', temporary, 'run', '--demo', '--port', String(port)]);
  await until(async () => (await fetch(origin)).ok, 'demo server');
  const profile = path.join(temporary, 'edge-profile');
  browser = launch(edge, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
  const debugging = await until(() => fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split(/\r?\n/)[0], 'Edge CDP');
  const page = await (await fetch(`http://127.0.0.1:${debugging}/json/new?${encodeURIComponent(origin)}`, { method: 'PUT' })).json();
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
  await send('Page.navigate', { url: origin });
  await until(() => evaluate('document.querySelectorAll("#market-rows tr[data-symbol]").length > 0 || document.querySelector("#market-rows")?.textContent.includes("BTC")'), 'real market rows');
  const routes = await evaluate('[...document.querySelectorAll("nav [data-view]")].map(node => node.dataset.view)');
  assert.equal(routes.length, 9);
  for (const route of routes) {
    await evaluate(`document.querySelector('nav [data-view="${route}"]').click()`);
    await until(() => evaluate(`document.querySelector('#v-${route}')?.hidden === false`), `navigation ${route}`);
  }
  await evaluate('document.querySelector("nav [data-view=markets]").click()');
  await evaluate('document.fonts.ready.then(() => true)');
  assert(await evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'desktop horizontal overflow');
  async function screenshot(name) {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    fs.writeFileSync(path.join(artifacts, name), Buffer.from(shot.data, 'base64'));
  }
  await screenshot('markets-desktop.png');
  await evaluate('document.querySelector("nav [data-view=research]").click()');
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
  assert.equal(comparison.funded_authority, false);
  assert.equal(comparison.order_submitted, false);
  assert.equal(comparison.runs.length, 2);
  assert.equal(comparison.runs[0].inputs.data, comparison.runs[1].inputs.data);
  assert.equal(comparison.runs[0].inputs.snapshots, comparison.runs[1].inputs.snapshots);
  await until(() => evaluate('document.querySelector("#compare-result").textContent.includes("ema-trend")'), 'rendered paper result');
  await screenshot('research-desktop.png');
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
  await evaluate('document.querySelector("#language-toggle").click()');
  assert.equal(await evaluate('document.documentElement.dir'), 'ltr');
  await screenshot('markets-mobile-en.png');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  assert(await evaluate('getComputedStyle(document.activeElement).outlineStyle !== "none"'), 'keyboard focus outline');
  assert.deepEqual(errors, [], 'browser exceptions');
  const report = { mode: 'DEMO', authority: 'PAPER_ONLY', funded_authority: false, routes, comparison_id: comparison.comparison_id,
    checks: ['nine real views', 'real paired replay and result rendering', 'identical decision/data windows', 'persisted form inputs', 'theme switch', 'EN/FA RTL switch', 'desktop/mobile overflow', 'keyboard focus', 'no JavaScript exceptions'] };
  fs.writeFileSync(path.join(artifacts, 'browser-report.json'), JSON.stringify(report, null, 2));
  console.log(`PASS: real Edge UI; screenshots/report: ${artifacts}`);
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
