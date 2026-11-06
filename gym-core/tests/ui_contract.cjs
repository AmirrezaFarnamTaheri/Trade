const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const page = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = [];
class Element {
  constructor(node) {
    this.tagName = node.tag.toUpperCase();
    this.attributes = { ...node.attrs };
    this.parentIndex = node.parent;
    this.dataset = {};
    for (const [key, value] of Object.entries(node.attrs)) this.setAttribute(key, value);
    this.textContent = "";
    this.innerHTML = "";
    this.value = node.attrs.value || "";
    this.hidden = "hidden" in node.attrs;
    this.disabled = "disabled" in node.attrs;
    this.style = {};
    this.listeners = {};
    this.classList = {
      add: (...names) => { this.className = [...new Set((this.className || "").split(/\s+/).concat(names))].join(" "); },
      remove: (...names) => { this.className = (this.className || "").split(/\s+/).filter(name => !names.includes(name)).join(" "); },
      toggle: (name, force) => { const add = force ?? !(this.className || "").split(/\s+/).includes(name); this.classList[add ? "add" : "remove"](name); },
    };
  }
  set textContent(value) { this._text = String(value ?? ""); this._html = ""; }
  get textContent() { return this._text || this._html.replace(/<[^>]*>/g, ""); }
  set innerHTML(value) {
    this._html = String(value ?? ""); this._text = "";
    // Only generated candidate controls need a parsed subtree in this harness.
    if (!/^candidate-(first|second)-params$/.test(this.id || "")) return;
    for (const element of elements) if (element.parentIndex === elements.indexOf(this)) { element.parentIndex = null; element.detached = true; }
    for (const match of this._html.matchAll(/<(input|select)\b([^>]*)(?:>([\s\S]*?)<\/select>)?/g)) {
      const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([, key, val]) => [key, val ?? ""]));
      const control = new Element({ tag: match[1], attrs, parent: elements.indexOf(this) });
      if (match[1] === "select") {
        const options = [...(match[3] || "").matchAll(/<option([^>]*)>([^<]*)<\/option>/g)];
        control.value = (options.find(option => option[1].includes("selected")) || options[0])?.[2] || "";
      }
      elements.push(control);
    }
  }
  get innerHTML() { return this._html; }
  setAttribute(key, value) {
    this.attributes[key] = String(value ?? "");
    if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value ?? "");
    if (key === "id") this.id = value;
    if (key === "class") this.className = value;
  }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll(selector) { return select(selector, this); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  checkValidity() { return this.valid !== false; }
  reportValidity() { return this.checkValidity(); }
  focus() {}
  scrollIntoView() {}
}
elements.push(...page.map(node => new Element(node)));
function matches(element, selector) {
  const attributes = [...selector.matchAll(/\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g)];
  let rest = selector.replace(/\[[^\]]*\]/g, "");
  for (const [, key, value] of attributes) {
    if (!(key in element.attributes) || (value !== undefined && element.attributes[key] !== value)) return false;
  }
  for (const [, id] of rest.matchAll(/#([\w-]+)/g)) if (element.id !== id) return false;
  for (const [, name] of rest.matchAll(/\.([\w-]+)/g)) if (!(element.className || "").split(/\s+/).includes(name)) return false;
  const tag = rest.match(/^[\w-]+/);
  return !tag || element.tagName.toLowerCase() === tag[0];
}
function ancestor(element) { return elements[element.parentIndex] || null; }
function inside(element, scope) { for (let parent = ancestor(element); parent; parent = ancestor(parent)) if (parent === scope) return true; return false; }
function select(selector, scope) {
  return elements.filter(element => !element.detached && (!scope || inside(element, scope)) && selector.split(",").some(part => {
    const chain = part.trim().split(/\s+/);
    if (!matches(element, chain.pop())) return false;
    let parent = ancestor(element);
    while (chain.length) {
      const wanted = chain.pop();
      while (parent && !matches(parent, wanted)) parent = ancestor(parent);
      if (!parent) return false;
      parent = ancestor(parent);
    }
    return true;
  }));
}
const byId = id => {
  const element = elements.find(e => !e.detached && e.id === id);
  assert.ok(element, `Application references missing page element #${id}`);
  return element;
};
const resolutions = ["1min", "3min", "5min", "15min", "30min", "1h", "2h", "4h", "6h", "12h", "1day"];
byId("gym-config").textContent = JSON.stringify({ token: "test-local-token", demo: true, resolutions });
const requests = [];
const replies = new Map([
  ["/api/markets", { now: "2026-11-02T08:00:00Z", demo: true, markets: [], universe: { observed_assets: [], observed_markets: 0 } }],
  ["/api/health", { demo: true, connected: false, fatal: null, reconnects: 0, last_frame_age_s: null, errors: [], quality: [] }],
  ["/api/runs", []], ["/api/rules", { version: 0, rules: [], quarantined: [] }],
  ["/api/research-state", { state: "NOT_CONFIGURED", authority: "PAPER_ONLY", funded_authority: false, order_submitted: false, hypotheses: [], jobs: [], alerts: [] }],
  ["/api/automation-safety", { mode: "DISARMED", protection: "UNAVAILABLE", venue_stops: "NOT_CERTIFIED", funded_authority: false, entries_enabled: false, autopilot_enabled: false, executor_state_verified: false }],
  ["/api/account-observations", { state: "NOT_CONFIGURED", authority: "READ_ONLY", balances: [], orders: [], exposure: [] }],
  ["/api/external-order-events", { events: [] }], ["/api/offline-ticket-reviews", { tickets: [], reviews: [] }],
  ["/api/venue-facts", { state: "NOT_CONFIGURED", facts: [], capabilities: {} }], ["/api/chaos-report", { state: "NOT_RUN" }],
]);
let responseStatus = 200;
let delayedTicket = null;
let delayedCompare = null;
let delayedSetup = null;
let abortHealth = false;
const strategies = [
  { id: "ema-trend", title: "EMA trend", parameters: { properties: { fast: { type: "integer", default: 8, minimum: 1, maximum: 10000 }, slow: { type: "integer", default: 21, minimum: 2, maximum: 10000 } } } },
  { id: "sma-reversion", title: "SMA reversion", parameters: { properties: { lookback: { type: "integer", default: 20, minimum: 2, maximum: 10000 }, entry_bps: { type: "integer", default: 50, minimum: 0, maximum: 1000 } } } },
  { id: "ema-confirmed", title: "Confirmed", parameters: { properties: { confirmation: { type: "string", default: "1h", enum: ["15min", "1h", "1day"] } } } },
  { id: "relative-momentum", title: "Relative", parameters: { properties: { reference: { type: "string", default: "ETHUSDT" } } } },
  { id: "bollinger-reversion", title: "Bollinger reversion", parameters: { properties: { lookback: { type: "integer", default: 20, minimum: 2, maximum: 10000 }, deviations: { type: "integer", default: 2, minimum: 1, maximum: 5 } } } },
];
const setup = { strategies, symbols: ["BTCUSDT"], coverage: { symbol: "BTCUSDT", observations: 30, from: "2026-10-29T12:30:00+03:30", to: "2026-10-29T13:00:00+03:30", gaps_over_120s: 0 }, defaults: { fee_rate: "0.001", resolution: "15min", latency_ms: 500 }, authority: "PAPER_ONLY", funded_authority: false };
replies.set("/api/research", setup);
replies.set("/api/research?symbol=BTCUSDT", setup);
const comparison = { comparison_id: "paired-test", mode: "COMPARE", authority: "PAPER_ONLY", funded_authority: false, order_submitted: false, shared_inputs: {}, ranking: { active: [] }, runs: ["a", "b"].map((id, i) => ({ run_id: id.repeat(16), inputs: { strategy: strategies[i].id, symbol: "BTCUSDT", params: {}, config_hash: id }, result: { symbol: "BTCUSDT", strategy: strategies[i].id, quote: "USDT", end: { net: "1.123456789012345678" }, fills: 2 } })) };
replies.set("/api/compare", comparison);
const httpReply = (data, status = responseStatus) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
const windowEvents = new Map();
const storage = new Map([["lang", "unsupported-language"], ["theme", "unsupported-theme"]]);
const timers = new Map();
let timerId = 0;
const sandbox = {
  document: {
    documentElement: elements.find(element => element.tagName === "HTML"), visibilityState: "visible", hidden: false,
    getElementById: byId, querySelectorAll: selector => select(selector), querySelector: selector => select(selector)[0] || null,
    addEventListener() {},
  },
  localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
  location: { hash: "" }, history: { replaceState() {} },
  addEventListener(name, callback) { windowEvents.set(name, callback); }, removeEventListener() {},
  matchMedia: () => ({ matches: false }),
  setInterval() {}, clearInterval() {},
  setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
  clearTimeout(id) { timers.delete(id); },
  console, Intl, URL, URLSearchParams, AbortController,
  confirm: () => false,
  fetch: async (path, options = {}) => {
    requests.push({ path, options });
    assert.ok(replies.has(path), `Unexpected API request: ${path}`);
    if ((path === "/api/research" || path.startsWith("/api/research?")) && delayedSetup) return delayedSetup;
    if (path === "/api/compare" && delayedCompare) return delayedCompare;
    if (path === "/api/health" && abortHealth) return new Promise((_, reject) => options.signal.addEventListener("abort", () => reject(new Error("aborted"))));
    if (path === "/api/dry-run/ticket" && delayedTicket) return delayedTicket;
    return httpReply(replies.get(path));
  },
};
sandbox.window = sandbox;
const context = vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context, { timeout: 5000 });
const app = vm.runInContext("({ T, num, esc, api, state, showView, renderMarkets, renderRun, renderHealth, editTicketField, renderTicketFields, healthyQuote, waterfallFigure, setupResearch, renderResearchJobs, controlResearch, accountJournal, serviceReceiptDetails })", context);
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(setImmediate); };
const plain = value => String(value).replace(/<[^>]*>/g, "");
const click = async id => {
  const element = byId(id);
  const handler = element.onclick || element.listeners.click;
  assert.equal(typeof handler, "function", `Button #${id} must be connected`);
  await handler({ target: element, preventDefault() {} });
  await settle();
};

(async () => {
  await settle();
  assert.equal(app.state.view, "overview");
  assert.equal(byId("v-overview").hidden, false);
  assert.equal(sandbox.document.documentElement.lang, "en", "Invalid saved language must fall back safely");
  assert.ok(requests.some(r => r.path === "/api/markets"), "Startup must load market data");
  assert.ok(byId("market-rows").innerHTML || byId("market-rows").textContent, "Empty markets need visible feedback");

  for (const element of elements) for (const name of ["t", "tPlaceholder", "tLabel"]) {
    const key = element.dataset[name];
    if (!key) continue;
    for (const language of ["en", "fa"]) assert.ok(app.T[language][key], `${language} translation missing for ${key}`);
  }
  assert.deepEqual(Object.keys(app.T.en).sort(), Object.keys(app.T.fa).sort(), "EN and FA need the same UI vocabulary");
  await click("language-toggle");
  assert.equal(sandbox.document.documentElement.lang, "fa");
  assert.equal(sandbox.document.documentElement.dir, "rtl");
  assert.equal(select('[data-t="navMarkets"]')[0].textContent, app.T.fa.navMarkets);
  await click("language-toggle");
  assert.equal(sandbox.document.documentElement.lang, "en");
  const originalTheme = sandbox.document.documentElement.dataset.theme;
  await click("theme-toggle");
  assert.notEqual(sandbox.document.documentElement.dataset.theme, originalTheme, "Theme button must change the theme");
  assert.equal(plain(app.num("12345678901234567890.123456789012345678")), "12,345,678,901,234,567,890.123456789012345678");
  assert.equal(plain(app.num("0")), "0");
  assert.equal(app.esc('<img src="x" onerror="x">&'), "&lt;img src=&quot;x&quot; onerror=&quot;x&quot;&gt;&amp;");
  const workbenchControls = new Map();
  const control = id => {
    if (!workbenchControls.has(id)) workbenchControls.set(id, { value: id === "research-action" ? "register" : "", querySelector: () => ({ disabled: false }) });
    return workbenchControls.get(id);
  };
  control("gym-config").textContent = JSON.stringify({ resolutions });
  const coverageRequests = [];
  const workbenchContext = vm.createContext({ window: {}, document: { documentElement: { lang: "en" }, getElementById: control } });
  vm.runInContext(fs.readFileSync(require("node:path").join(require("node:path").dirname(process.argv[2]), "research.js"), "utf8"), workbenchContext);
  for (const language of ["en", "fa"]) {
    workbenchContext.document.documentElement.lang = language;
    workbenchContext.window.gymResearch.mount(async (path, options) => { coverageRequests.push({ path, body: JSON.parse(options.body) }); return {}; }, app.esc);
    for (const resolution of resolutions) assert.ok(control("research-workspace").innerHTML.includes(`<option>${resolution}</option>`), "Coverage must expose the shared timeframe catalogue in both languages");
    control("coverage-symbol").value = "BTCUSDT";
    control("coverage-from").value = "2026-11-05T00:00";
    control("coverage-to").value = "2026-11-06T00:00";
    control("coverage-resolution").value = "4h";
    control("coverage-form").onsubmit({ preventDefault() {}, target: control("coverage-form") });
    await settle();
    assert.equal(coverageRequests.at(-1).body.value.resolution, "4h", "Coverage must send the selected timeframe to the backend");
  }
  const receipt = {resource:'BALANCES',sequence:'9007199254740993',runtime_epoch:'10',started_at_ms:'1000',received_at_ms:'1010',credential_generation:'33'.repeat(16),request_id:'11'.repeat(16),response_digest:'44'.repeat(32),event_hash:'55'.repeat(32)};
  assert.equal(app.serviceReceiptDetails(undefined), '');
  const orderReceipt = {...receipt,resource:'ORDER_STATUS',client_id:'manual-1'};
  const pageReceipt = {...receipt,resource:'OPEN_ORDERS',page:'2',per_page:'10'};
  const historyReceipt = {...receipt,resource:'ORDER_HISTORY',page:'1',per_page:'10'};
  const orderEvidence = {client_id:'manual-1',symbol:'BTCUSDT',side:'BUY',raw_status:'CANCELED',requested_qty:'1',executed_qty:'0.1',fill_coverage:'REPORTED_QUANTITY_MATCHES',settlement:'UNKNOWN',fills:[{quantity:'0.1',price:'100',fee:'0.000000000000000001',fee_asset:'BTC',timestamp:1762390000000}]};
  replies.set('/api/account-observations', {state:'OBSERVED',account_id:'main',observed_at:'2026-11-05T16:00:00Z',balances:[],orders:[],exposure:[],service_receipts:[receipt,orderReceipt,pageReceipt,historyReceipt],order_evidence:[orderEvidence],order_pages:[{kind:'OPEN',requested_page:2,requested_per_page:10,pagination_echo:'UNVERIFIED',settlement:'UNKNOWN',orders:[orderEvidence]}],fee_rates:{BTCUSDT:{maker:'0.001000000000000001',taker:'0.002'}}});
  for (const language of ['en','fa']) {
    if (sandbox.document.documentElement.lang !== language) await click('language-toggle');
    await app.accountJournal();
    const output = byId('account-observations').innerHTML;
    assert.ok(output.includes(app.T[language].serviceReceiptsNote));
    assert.ok(output.includes(app.T[language].accountFeeNote));
    assert.ok(output.includes(app.T[language].receiptOrder));
    assert.ok(output.includes(app.T[language].receiptOpenOrders));
    assert.ok(output.includes(app.T[language].receiptHistory));
    assert.ok(output.includes(app.T[language].orderPagesNote));
    assert.ok(output.includes(app.T[language].paginationEcho));
    assert.ok(output.includes(app.T[language].UNVERIFIED));
    assert.ok(output.includes(app.T[language].orderDetailsNote));
    assert.ok(output.includes(app.T[language].REPORTED_QUANTITY_MATCHES));
    assert.ok(output.includes('BTC') && output.includes('manual-1'));
    assert.ok(output.includes(language === 'en' ? '0.000000000000000001' : '۰.۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۰۱'), 'Fill fees must remain exact');
    assert.ok(output.includes(language === 'en' ? '0.001000000000000001' : '۰.۰۰۱۰۰۰۰۰۰۰۰۰۰۰۰۰۰۱'), 'Recorded fee strings must remain exact');
    assert.ok(output.includes('9007199254740993'), 'Journal sequences must retain exact decimal strings');
    assert.match(output, /<details><summary>/);
  }
  if (sandbox.document.documentElement.lang !== 'en') await click('language-toggle');
  const escapedReceipt = app.serviceReceiptDetails([{...receipt,event_hash:'<img src=x onerror=x>',received_at_ms:'<script>x</script>'}]);
  assert.doesNotMatch(escapedReceipt, /<img|<script/);
  assert.match(escapedReceipt, /&lt;img/);
  const costs = [["directional", "100"], ["spread", "-10"], ["fees", "-5"], ["latency_drift", "-2"], ["net", "83"]];
  const waterfall = app.waterfallFigure(costs, '<img src="x">&');
  assert.equal((waterfall.match(/<rect\b/g) || []).length, 5, "Cost waterfall must include each step and the net total");
  assert.doesNotMatch(waterfall, /NaN|Infinity|<img\b/);
  assert.ok(waterfall.includes("&lt;img src=&quot;x&quot;&gt;&amp;"), "Chart currency must be escaped");
  for (const invalid of ["NaN", "Infinity", "-Infinity"]) assert.equal(app.waterfallFigure([["net", invalid]], "USDT"), "");
  const zeroWaterfall = app.waterfallFigure(costs.map(([key]) => [key, "0"]), "USDT");
  assert.equal((zeroWaterfall.match(/<rect\b/g) || []).length, 5);
  assert.doesNotMatch(zeroWaterfall, /NaN|Infinity/);
  app.renderRun({ run_id: "1234567890abcdef", inputs: { store: "demo" }, evidence: {
    sampled_drawdown: { status: "AVAILABLE", maximum_percent: "1.12345678" },
  }, result: { symbol: "BTCUSDT", quote: "USDT", end: {
    equity: "1000.123456789012345678", net: "83.123456789012345678", waterfall: Object.fromEntries(costs),
  } } });
  assert.ok(byId("run-detail").innerHTML.includes("1,000.123456789012345678"), "Chart rounding must not round the exact equity statistic");
  assert.ok(byId("run-detail").innerHTML.includes("83.123456789012345678"), "Chart rounding must not round the exact net statistic");
  assert.ok(byId("run-detail").innerHTML.includes("1.12345678"));
  assert.ok(byId("run-detail").innerHTML.includes('data-export-run="1234567890abcdef"'));
  replies.set("/api/runs/1234567890abcdef/summary", {});
  responseStatus = 503;
  const exportButton = { dataset: { exportRun: "1234567890abcdef" }, disabled: false };
  await byId("run-detail").listeners.click({ target: exportButton });
  assert.equal(exportButton.disabled, false, "Failed download must allow retry");
  assert.equal(app.state.apiError, true);
  assert.equal(byId("connection-error").hidden, false, "Download failure needs visible feedback");
  responseStatus = 200;
  for (const raw of ["null", "[]", "42", '"text"', "true"]) {
    byId("offline-ticket").value = raw;
    assert.doesNotThrow(() => app.renderTicketFields(), `Structured form must tolerate JSON ${raw}`);
    assert.equal(byId("offline-ticket").value, raw, "Switching editors must retain invalid ticket text for correction");
    assert.ok(byId("ticket-fields").innerHTML.includes('data-ticket-field="quantity"'));
  }

  const blocked = {
    allowed: false, next_change: "2026-11-02T09:00:00Z", quota_remaining: "10", warnings: [],
    blockers: [
      { name: "Night closure", class: "VENUE", family: "closure", status: "CONFIRMED", source: "operator" },
      { name: "Balance limit", class: "VENUE", family: "quota", status: "INFERRED", source: "observed" },
    ],
  };
  app.state.markets = {
    ...replies.get("/api/markets"),
    capabilities: { collection: { mode: "all-spot" }, catalog_markets: 2, asset_capacity: 500, resolutions, venue_candle_fetch_resolutions: ["1min", "1h"] },
    catalog: [{ symbol: "BTCUSDT", base: "BTC", quote: "USDT", reason: "OBSERVING", risk_flagged: false },
      { symbol: '<script>EUR', base: "TEST", quote: "EUR", reason: "UNSUPPORTED_QUOTE", risk_flagged: true }],
    markets: [{
      symbol: "BTCUSDT", base: "BTC", quote: "USDT", names: { en: '<img src="x" onerror="x">', fa: "بیت‌کوین" },
      bid: "12345678901234567890.123456789012345678", ask: "12345678901234567891", bid_qty: "1", ask_qty: "2",
      spread: "0.5", spread_bps: "2", flags: ["STALE"], book_age_s: 40, last_trade: null,
      act: { entry: blocked, exit: { allowed: true, blockers: [], warnings: [], next_change: null, quota_remaining: null } },
    }],
  };
  app.state.expanded = "BTCUSDT";
  app.renderMarkets();
  assert.ok(byId("market-capabilities").innerHTML.includes("12h"), "Capability display must use the runtime timeframe catalogue");
  assert.ok(byId("market-capabilities").innerHTML.includes(app.T.en.financingScopeNote), "Short and leverage diagnostics must not imply executable positions");
  assert.ok(byId("market-catalogue").innerHTML.includes(app.T.en.UNSUPPORTED_QUOTE), "Unobserved listings need their exclusion reason");
  assert.ok(!byId("market-catalogue").innerHTML.includes("<script>"), "Public catalogue fields must be escaped");
  const marketHTML = byId("market-rows").innerHTML;
  assert.ok(marketHTML.includes("Night closure") && marketHTML.includes("Balance limit"), "Expanded pair must disclose every blocker");
  assert.ok(marketHTML.includes("12,345,678,901,234,567,890.123456789012345678"), "Market rendering must retain decimal precision");
  assert.ok(!marketHTML.includes('<img src="x"'), "Venue display names must be escaped");
  assert.doesNotMatch(marketHTML, /\bopens\b/i, "Next rule change must not promise an opening");
  app.state.filter = "not-a-watched-pair";
  app.renderMarkets();
  assert.ok(!byId("market-catalogue").innerHTML.includes("BTCUSDT"), "Search must also filter the complete catalogue");
  assert.ok(!byId("market-rows").innerHTML.includes("BTCUSDT"), "Search must filter market rows");
  app.state.filter = "";
  app.state.quote = "TMN";
  app.renderMarkets();
  assert.ok(!byId("market-rows").innerHTML.includes("BTCUSDT"), "Quote selection must filter market rows");
  app.state.quote = "";
  const watched = app.state.markets.markets[0];
  const scientific = { ...watched, symbol: "TINYUSDT", bid: "1E-8", ask: "2E-8", flags: [], qualified: true };
  const crossed = { ...watched, symbol: "CROSSEDUSDT", bid: "2E-8", ask: "1E-8", flags: [], qualified: false };
  const unassessed = { ...watched, symbol: "UNKNOWNUSDT", flags: [] };
  assert.equal(app.healthyQuote(scientific), true, "Domain-qualified scientific quotes are healthy");
  assert.equal(app.healthyQuote(crossed), false, "Unflagged crossed quotes must not be counted as healthy");
  assert.equal(app.healthyQuote(unassessed), false, "Missing domain qualification must not imply healthy quotes");
  app.state.markets = { ...app.state.markets, markets: [scientific, crossed, unassessed] };
  app.state.expanded = "";
  app.renderMarkets();
  assert.ok(byId("market-summary").innerHTML.includes(`${app.T.en.healthyQuotes}</span><strong class="stat-value">1</strong>`), "Summary must count domain-qualified quotes only");
  assert.ok(byId("market-rows").innerHTML.includes(app.T.en.notEvaluated), "An unqualified, unflagged row needs an unknown state");

  for (const name of ["overview", "research", "account", "operate", "rules", "health", "safety", "backups", "markets"]) {
    await app.showView(name);
    await settle();
    if (name === "research") {
      for (const resolution of resolutions) assert.ok(byId("compare-resolution").innerHTML.includes(`<option>${resolution}</option>`), "Comparison must expose every shared fixed timeframe");
    }
    for (const section of elements.filter(e => e.id?.startsWith("v-"))) assert.equal(section.hidden, section.id !== "v-" + name);
    for (const button of select("[data-view]")) assert.equal(button.getAttribute("aria-current"), button.dataset.view === name ? "page" : null);
  }
  const hashchange = windowEvents.get("hashchange");
  assert.equal(typeof hashchange, "function", "Hash navigation must be connected");
  sandbox.location.hash = "#main";
  await hashchange();
  await settle();
  assert.equal(app.state.view, "markets", "Skip-to-content hash must retain the selected view");
  assert.equal(byId("v-markets").hidden, false);
  sandbox.location.hash = "";
  await hashchange();
  await settle();
  assert.equal(app.state.view, "overview", "Returning to an empty hash must open Overview");
  assert.equal(byId("v-overview").hidden, false);
  const safetyReply = replies.get("/api/automation-safety");
  replies.set("/api/automation-safety", {
    mode: "ARMED", protection: "ACTIVE", venue_stops: "CERTIFIED", funded_authority: true,
    entries_enabled: true, autopilot_enabled: true, executor_state_verified: true,
  });
  await app.showView("operate");
  await settle();
  const protection = byId("protection-state").textContent + byId("protection-state").innerHTML;
  assert.doesNotMatch(protection, /\bARMED\b|\bACTIVE\b|\bCERTIFIED\b/, "Unsupported safety status must not imply trading authority");
  for (const entries_enabled of ["false", 0, undefined]) {
    replies.set("/api/automation-safety", { ...safetyReply, entries_enabled });
    await app.showView("operate");
    await settle();
    assert.ok(byId("protection-state").textContent.includes(app.T.en.protectionUnavailable), "Malformed entry authority must be unavailable");
  }
  replies.set("/api/automation-safety", safetyReply);
  const preview = () => click("preview-ticket");
  const ticketText = () => byId("ticket-output").textContent + byId("ticket-output").innerHTML;
  const rawTicket = '{"quantity":"1","quantity":"2","api_key":"PRIVATE-INPUT-MUST-NOT-ECHO"}';
  byId("offline-ticket").value = rawTicket;
  replies.set("/api/dry-run/ticket", { error: "Invalid offline ticket" });
  responseStatus = 400;
  await preview();
  assert.equal(requests.at(-1).path, "/api/dry-run/ticket");
  assert.equal(requests.at(-1).options.method, "POST");
  assert.equal(requests.at(-1).options.body, rawTicket, "Keep original JSON so backend can reject duplicate keys");
  assert.ok(!ticketText().includes("PRIVATE-INPUT-MUST-NOT-ECHO"), "Failed previews must not echo private input");
  const ticket = {
    symbol: "BTCUSDT", side: "BUY", intent: "ENTRY", quantity: "0.01", bid: "100", ask: "101", worst_price: "103",
    fee_rate: "0.002", operator_quote_cap: "2", available_quote: "2", available_base: "0", minimum_quote: "1",
    observed_at: "2026-11-02T08:00:00Z", expires_at: "2026-11-02T08:00:30Z", snapshot_seq: 5, quote_age_ms: 10,
  };
  const safePreview = {
    ...ticket, estimated_gross_quote: "1.01", worst_gross_quote: "1.03", worst_fee_quote: "0.00206", worst_total_quote: "1.03206",
    break_even_bid: "103.412826", mode: "DRY_RUN", source: "OFFLINE_PREVIEW", fee_assumption: "QUOTE_ONLY_UNVERIFIED",
    client_id: null, funded_authority: false, order_submitted: false, preview_sha256: "a".repeat(64),
  };
  byId("offline-ticket").value = JSON.stringify(ticket);
  replies.set("/api/dry-run/ticket", safePreview);
  responseStatus = 200;
  await preview();
  assert.ok(ticketText().includes("BTCUSDT"), "Valid offline preview must show its instrument");

  const fields = Object.entries(ticket).map(([key, value]) => ({ dataset: { ticketField: key }, value: String(value) }));
  fields.find(field => field.dataset.ticketField === "quantity").value = "12345678901234567890.123456789012345678";
  const fieldContainer = byId("ticket-fields"), originalQuery = fieldContainer.querySelectorAll.bind(fieldContainer);
  fieldContainer.querySelectorAll = selector => selector === "[data-ticket-field]" ? fields : originalQuery(selector);
  app.editTicketField();
  const structured = JSON.parse(byId("offline-ticket").value);
  assert.deepEqual(Object.keys(structured).sort(), Object.keys(ticket).sort(), "Structured form must preserve the exact offline request fields");
  assert.equal(structured.quantity, "12345678901234567890.123456789012345678");
  for (const [key, value] of Object.entries(structured)) assert.equal(typeof value, ["snapshot_seq", "quote_age_ms"].includes(key) ? "number" : "string", `Incorrect request type for ${key}`);
  assert.equal(structured.snapshot_seq, 5);
  assert.equal(structured.quote_age_ms, 10);
  assert.ok(ticketText().includes(app.T.en.previewChanged), "Editing structured inputs must invalidate the old cost result");
  fields.find(field => field.dataset.ticketField === "snapshot_seq").value = "9007199254740993";
  fields.find(field => field.dataset.ticketField === "quote_age_ms").value = "invalid";
  app.editTicketField();
  const invalidMetadata = JSON.parse(byId("offline-ticket").value);
  assert.equal(invalidMetadata.snapshot_seq, "9007199254740993", "Unsafe sequence integers must reach validation without rounding");
  assert.equal(invalidMetadata.quote_age_ms, "invalid", "Invalid metadata must not be silently coerced");
  fieldContainer.querySelectorAll = originalQuery;

  byId("offline-ticket").value = JSON.stringify(ticket);
  await preview();
  const onTicketInput = byId("offline-ticket").listeners.input;
  assert.equal(typeof onTicketInput, "function", "JSON changes must invalidate previews");
  byId("offline-ticket").value = JSON.stringify({ ...ticket, quantity: "0.02" });
  onTicketInput();
  assert.ok(ticketText().includes(app.T.en.previewChanged));
  assert.ok(!ticketText().includes("BTCUSDT"), "Changing JSON must clear the previous cost result");

  for (const [dispatchInput, status] of [[true, 200], [false, 200], [true, 400]]) {
    byId("offline-ticket").value = JSON.stringify(ticket);
    let resolveTicket;
    delayedTicket = new Promise(resolve => { resolveTicket = resolve; });
    const pendingPreview = byId("preview-ticket").onclick();
    await settle();
    assert.equal(byId("preview-ticket").disabled, true);
    byId("offline-ticket").value = JSON.stringify({ ...ticket, quantity: "0.03" });
    if (dispatchInput) onTicketInput();
    resolveTicket(httpReply({ ...safePreview, symbol: "STALE-TICKET-RESPONSE" }, status));
    await pendingPreview;
    delayedTicket = null;
    assert.ok(!ticketText().includes("STALE-TICKET-RESPONSE"), "Responses for edited inputs must be ignored, including programmatic edits");
    if (dispatchInput) {
      assert.ok(ticketText().includes(app.T.en.previewChanged));
      assert.equal(byId("offline-ticket").getAttribute("aria-invalid"), null, "Old failures must not invalidate edited inputs");
    }
    assert.equal(byId("preview-ticket").disabled, false);
  }
  byId("offline-ticket").value = JSON.stringify(ticket);
  for (const forged of [{ funded_authority: true }, { order_submitted: true }, { mode: "LIVE" }]) {
    replies.set("/api/dry-run/ticket", { ...safePreview, ...forged, symbol: "FORGED-AUTHORITY" });
    await preview();
    assert.ok(!ticketText().includes("FORGED-AUTHORITY"), "Unexpected trading authority must never appear as a valid preview");
  }
  const form = byId("compare-form");
  const submit = () => form.listeners.submit({ preventDefault() {} });
  const comparisonText = () => byId("compare-result").textContent;
  const edit = target => form.listeners.input({ target });
  await app.showView("research");
  await settle();
  assert.equal(byId("compare-from").value, "2026-10-29T09:00:00", "Coverage dates must be converted to UTC, not browser local time");
  assert.equal(byId("compare-to").value, "2026-10-29T09:30:00");
  assert.equal(byId("comparison-fields").disabled, false);
  assert.equal(byId("parameter-first-fast").value, "8");
  assert.equal(byId("parameter-first-fast").getAttribute("min"), "1");
  assert.equal(byId("parameter-second-lookback").value, "20");
  byId("compare-resolution").value = "1min";
  const exactCash = "12345678901234567890.123456789012345678";
  const exactFee = "0.001234567890123456789";
  byId("compare-cash").value = exactCash;
  byId("compare-fee").value = exactFee;
  const fast = byId("parameter-first-fast");
  fast.value = "3"; edit(fast);
  await submit();
  const sent = JSON.parse(requests.findLast(request => request.path === "/api/compare").options.body);
  assert.equal(sent.cash, exactCash); assert.equal(sent.fee_rate, exactFee);
  assert.equal(sent.from, "2026-10-29T09:00:00Z"); assert.equal(sent.to, "2026-10-29T09:30:00Z");
  assert.equal(sent.resolution, "1min"); assert.equal(sent.latency_ms, 500);
  assert.deepEqual(sent.candidates, [{ strategy: "ema-trend", params: { fast: 3, slow: 21 } }, { strategy: "sma-reversion", params: { lookback: 20, entry_bps: 50 } }]);
  assert.ok(comparisonText().includes("paired-test"));
  assert.ok(comparisonText().includes("1.123456789012345678"));
  assert.ok(byId("compare-result").innerHTML.includes('data-run="bbbbbbbbbbbbbbbb"'));
  assert.ok(comparisonText().includes(app.T.en.comparisonLimit));
  edit(byId("compare-cash"));
  assert.equal(app.state.comparison, null);
  assert.ok(comparisonText().includes(app.T.en.comparisonChanged));

  byId("candidate-first").value = "bollinger-reversion";
  byId("candidate-first").listeners.change();
  const deviations = byId("parameter-first-deviations");
  assert.equal(deviations.value, "2");
  assert.equal(deviations.getAttribute("max"), "5");
  deviations.value = "1"; edit(deviations);
  await submit();
  assert.deepEqual(JSON.parse(requests.findLast(request => request.path === "/api/compare").options.body).candidates[0],
    { strategy: "bollinger-reversion", params: { lookback: 20, deviations: 1 } });

  // Generated enum and string parameters must remain strings in requests.
  for (const [slot, strategy] of [["first", "ema-confirmed"], ["second", "relative-momentum"]]) {
    byId("candidate-" + slot).value = strategy;
    byId("candidate-" + slot).listeners.change();
  }
  assert.equal(select('[data-parameter="confirmation"]', byId("candidate-first-params"))[0].value, "1h");
  assert.equal(select('[data-parameter="reference"]', byId("candidate-second-params"))[0].value, "ETHUSDT");
  await submit();
  const stringParams = JSON.parse(requests.findLast(request => request.path === "/api/compare").options.body).candidates;
  assert.equal(stringParams[0].params.confirmation, "1h"); assert.equal(stringParams[1].params.reference, "ETHUSDT");

  for (const language of ["en", "fa"]) {
    if (sandbox.document.documentElement.lang !== language) await click("language-toggle");
    await submit();
    assert.ok(comparisonText().includes(app.T[language].comparisonLimit));
    assert.ok(comparisonText().includes("paired-test"));
    responseStatus = 400;
    await submit();
    assert.ok(comparisonText().includes(app.T[language].compareError));
    responseStatus = 200;
    for (const forged of [{ funded_authority: true }, { order_submitted: true }, { mode: "LIVE" }, { authority: "FUNDED" }, { funded_authority: "false" }]) {
      replies.set("/api/compare", { ...comparison, ...forged, comparison_id: "FORGED-COMPARISON" });
      await submit();
      assert.equal(app.state.comparison, null);
      assert.ok(!comparisonText().includes("FORGED-COMPARISON"));
      assert.ok(comparisonText().includes(app.T[language].compareError));
    }
    replies.set("/api/compare", comparison);
    for (const [dispatchInput, status] of [[true, 200], [false, 200], [true, 400], [false, 400]]) {
      let resolveCompare;
      delayedCompare = new Promise(resolve => { resolveCompare = resolve; });
      const pending = submit();
      await settle();
      assert.equal(byId("compare-submit").disabled, true);
      assert.equal(byId("compare-submit").getAttribute("aria-busy"), "true");
      assert.ok(comparisonText().includes(app.T[language].comparing));
      const count = requests.length;
      await submit(); assert.equal(requests.length, count, "No duplicate pending comparisons");
      byId("compare-cash").value += "1";
      if (dispatchInput) edit(byId("compare-cash"));
      resolveCompare(httpReply({ ...comparison, comparison_id: "STALE-COMPARISON" }, status));
      await pending; delayedCompare = null;
      assert.equal(app.state.comparison, null);
      assert.ok(!comparisonText().includes("STALE-COMPARISON"));
      assert.ok(comparisonText().includes(app.T[language].comparisonChanged));
      assert.equal(byId("compare-submit").disabled, false);
      assert.equal(byId("compare-submit").getAttribute("aria-busy"), null);
    }
    replies.set("/api/research?symbol=BTCUSDT", { ...setup, coverage: { ...setup.coverage, observations: 0, from: null, to: null } });
    await app.setupResearch("BTCUSDT");
    assert.equal(byId("comparison-fields").disabled, true);
    const count = requests.length; await submit(); assert.equal(requests.length, count, "No coverage must prevent submission");
    replies.set("/api/research?symbol=BTCUSDT", setup);
    await app.setupResearch("BTCUSDT");
    responseStatus = 503;
    await app.setupResearch("BTCUSDT");
    assert.equal(byId("comparison-fields").disabled, true, "Failed coverage must not leave old inputs enabled");
    assert.ok(byId("paper-coverage").textContent.includes(app.T[language].researchUnavailable));
    responseStatus = 200; await app.setupResearch("BTCUSDT");
    form.valid = false;
    const beforeInvalid = requests.length; await submit(); assert.equal(requests.length, beforeInvalid);
    form.valid = true;
  }
  if (sandbox.document.documentElement.lang !== "en") await click("language-toggle");
  replies.set("/api/runs", comparison.runs);
  for (const record of comparison.runs) replies.set("/api/runs/" + record.run_id, record);
  await submit();
  byId("compare-result").listeners.click({ target: { dataset: { run: "bbbbbbbbbbbbbbbb" } } });
  await settle();
  assert.equal(app.state.selectedRun, "bbbbbbbbbbbbbbbb");
  assert.equal(app.state.record.run_id, "bbbbbbbbbbbbbbbb");
  assert.ok(requests.some(request => request.path === "/api/runs/bbbbbbbbbbbbbbbb"));

  let resolveSetup;
  delayedSetup = new Promise(resolve => { resolveSetup = resolve; });
  const loadingSetup = app.setupResearch("BTCUSDT");
  assert.equal(byId("comparison-fields").disabled, true, "Coverage loading must disable stale inputs");
  const beforeCoverage = requests.length; await submit(); assert.equal(requests.length, beforeCoverage);
  resolveSetup(httpReply(setup)); await loadingSetup; delayedSetup = null;
  assert.equal(byId("comparison-fields").disabled, false);

  const jobs = { state: "CONFIGURED", authority: "PAPER_ONLY", funded_authority: false, order_submitted: false,
    hypotheses: [{ id: "hypothesis", strategy: "ema-trend", symbol: "BTCUSDT" }],
    jobs: [{ id: "job1", hypothesis_id: "hypothesis", enabled: true, next_at: "2026-11-03T08:00:00Z", last_report: { status: "FAILED", retry_at: "2026-11-03T09:00:00Z" } }],
    alerts: [{ kind: "RESEARCH_FAILED", due_at: "2026-11-03T08:00:00Z" }] };
  replies.set("/api/research-state", jobs);
  await app.showView("research"); await settle();
  assert.match(byId("research-jobs").innerHTML, /ema-trend/);
  assert.match(byId("research-jobs").innerHTML, /data-research-action="pause"/);
  assert.equal(byId("research-tick").disabled, false);
  replies.set("/api/research/jobs/job1/pause", { authority: "PAPER_ONLY", funded_authority: false, order_submitted: false, enabled: false });
  jobs.jobs[0].enabled = false;
  await app.controlResearch("pause", "job1");
  assert.match(byId("research-jobs").innerHTML, /data-research-action="resume"/);
  assert.equal(byId("research-tick").disabled, true);
  assert.equal(requests.find(row => row.path === "/api/research/jobs/job1/pause").options.body, "{}");
  app.renderHealth({ quality: [], errors: [], readiness: { status: "DEGRADED", markets: [{ symbol: "BTCUSDT", state: "STALE", bid_age_seconds: 121, ask_age_seconds: 4 }] } });
  assert.match(byId("health-readiness").innerHTML, /121/);
  const validation = { ...comparison, mode: "TEMPORAL_VALIDATION", validation_id: "abc", status: "EVALUATED", selected: { strategy: "ema-trend" },
    windows: { selection: { from: setup.coverage.from, to: setup.coverage.to }, holdout: { from: setup.coverage.from, to: setup.coverage.to } }, selection: { run_ids: [] }, trial_count: 3 };
  replies.set("/api/validate", validation);
  await click("validate-submit");
  assert.ok(requests.some(row => row.path === "/api/validate"));
  assert.match(byId("compare-result").innerHTML, /Chronological validation/);
  assert.equal(JSON.parse(requests.filter(row => row.path === "/api/validate").at(-1).options.body).folds, 1);
  const multi = { ...validation, mode: "MULTI_WINDOW_VALIDATION", fold_count: 2,
    status: "INCOMPLETE", folds: [validation, { ...validation, status: "ABSTAIN", selected: null }] };
  byId("validation-folds").value = "2";
  replies.set("/api/validate", multi);
  for (const language of ["en", "fa"]) {
    if (sandbox.document.documentElement.lang !== language) await click("language-toggle");
    await click("validate-submit");
    assert.equal(JSON.parse(requests.filter(row => row.path === "/api/validate").at(-1).options.body).folds, 2);
    assert.ok(byId("compare-result").innerHTML.includes(app.T[language].INCOMPLETE));
    assert.ok(byId("compare-result").innerHTML.includes(app.T[language].ABSTAIN));
    edit(byId("validation-folds"));
    assert.equal(app.state.comparison, null, "Changing windows invalidates the displayed evaluation");
  }
  byId("validation-folds").value = "1";

  const baselineTimers = timers.size;
  await app.api("/api/health"); assert.equal(timers.size, baselineTimers, "Success must clear request timer");
  responseStatus = 503;
  await assert.rejects(app.api("/api/health")); assert.equal(timers.size, baselineTimers, "HTTP errors must clear request timer");
  responseStatus = 200;
  abortHealth = true;
  const timedOut = assert.rejects(app.api("/api/health", {}, 17));
  const timeout = [...timers.values()].find(timer => timer.delay === 17);
  assert.ok(timeout); timeout.callback(); await timedOut;
  abortHealth = false;
  assert.equal(timers.size, baselineTimers, "Aborted requests must clear their timer");
  for (const request of requests) assert.equal(request.options.headers["X-Gym-Token"], "test-local-token");
  responseStatus = 503;
  await assert.rejects(app.api("/api/health"));
  responseStatus = 200;
  console.log("UI runtime contracts passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
