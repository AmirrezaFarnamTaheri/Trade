"use strict";
// Account observations, offline tickets, venue rules and operational health.
function serviceReceiptDetails(receipts) {
  if (!list(receipts).length) return "";
  const stamp = value => {
    const date = new Date(Number(value));
    return Number.isFinite(date.getTime()) ? when(date.toISOString()) : String(value);
  };
  return `<h3>${esc(t("serviceReceipts"))}</h3><p class="field-help">${esc(t("serviceReceiptsNote"))}</p>` + list(receipts).map(row =>
    `<details><summary>${esc(t(({BALANCES:"receiptBalances",FEES:"receiptFees",ORDER_STATUS:"receiptOrder",OPEN_ORDERS:"receiptOpenOrders",ORDER_HISTORY:"receiptHistory"})[row.resource] || "UNKNOWN"))}${row.client_id ? ` · ${esc(row.client_id)}` : ""}${row.page ? ` · ${esc(t("pageNumber"))} ${esc(row.page)} / ${esc(row.per_page)}` : ""} · ${esc(stamp(row.received_at_ms))} · ${esc(t("receiptEntry"))} ${esc(row.sequence)}</summary>${keyValues([
      [t("receiptRequested"), esc(stamp(row.started_at_ms))], [t("receiptReceived"), esc(stamp(row.received_at_ms))],
      [t("receiptRuntime"), code(row.runtime_epoch)], [t("receiptGeneration"), code(row.credential_generation)],
      [t("receiptRequest"), code(row.request_id)], [t("receiptResponse"), code(row.response_digest)],
      [t("receiptEvent"), code(row.event_hash)],
    ])}</details>`).join("");
}
function orderEvidenceDetails(evidence) {
  if (!list(evidence).length) return "";
  return `<h3>${esc(t("orderDetails"))}</h3><p class="field-help">${esc(t("orderDetailsNote"))}</p>` + list(evidence).map(row =>
    `<details><summary>${esc(row.client_id)} · ${esc(row.symbol)} · ${esc(row.raw_status)}</summary>${keyValues([
      [t("side"), esc(row.side)], [t("requestedQuantity"), amount(row.requested_qty)],
      [t("filledObserved"), amount(row.executed_qty)], [t("fillCoverage"), esc(t(row.fill_coverage))],
      [t("settlement"), esc(t(row.settlement))],
    ])}${table([t("fillTimestamp"), t("quantity"), t("fillPrice"), t("fillFee"), t("fillFeeAsset")],
      list(row.fills).map(fill => [code(String(fill.timestamp)), amount(fill.quantity), amount(fill.price), amount(fill.fee), code(fill.fee_asset)]), t("noReportedFills"))}</details>`).join("");
}
function orderPageDetails(pages) {
  if (!list(pages).length) return "";
  return `<h3>${esc(t("orderPages"))}</h3><p class="field-help">${esc(t("orderPagesNote"))}</p>` + list(pages).map(page =>
    `<details><summary>${esc(t(page.kind === "OPEN" ? "receiptOpenOrders" : "receiptHistory"))} · ${esc(page.requested_page)}</summary>${keyValues([
      [t("pageNumber"), esc(page.requested_page)], [t("perPage"), esc(page.requested_per_page)],
      [t("paginationEcho"), esc(t(page.pagination_echo))], [t("settlement"), esc(t(page.settlement))],
    ])}${table([t("clientId"), t("pair"), t("rawStatus"), t("filledObserved")], list(page.orders).map(row =>
      [code(row.client_id), code(row.symbol), esc(row.raw_status), amount(row.executed_qty)]), t("noAccountOrders"))}</details>`).join("");
}
async function accountJournal() {
  const summary = $("account-state");
  try {
    const observation = await api("/api/account-observations");
    if (observation.state === "NOT_CONFIGURED") {
      summary.textContent = t("accountNotConfigured");
      setHTML("account-observations", `<p class="field-help">${esc(t("accountSetupHelp"))}</p>`);
      return;
    }
    if (observation.state !== "OBSERVED") throw new Error(t("accountError"));
    summary.textContent = `${t("accountObserved")} · ${observation.account_id || ""} · ${when(observation.observed_at)}`;
    setHTML("account-observations", `${serviceReceiptDetails(observation.service_receipts)}<h3>${esc(t("accountBalance"))}</h3><p class="field-help">${esc(t("accountBalanceNote"))}</p>${table([t("asset"), t("venueValue"), t("venueLocked")], list(observation.balances).map(row => [code(row.asset), amount(row.venue_value), amount(row.venue_locked)]), t("noBalances"))}
      <h3>${esc(t("accountFeeRates"))}</h3><p class="field-help">${esc(t("accountFeeNote"))}</p>${table([t("pair"), t("makerFeeRate"), t("takerFeeRate")], Object.entries(observation.fee_rates || {}).map(([symbol, row]) => [code(symbol), amount(row.maker), amount(row.taker)]), t("noAccountFees"))}
      <h3>${esc(t("accountOrders"))}</h3>${table([t("clientId"), t("pair"), t("rawStatus"), t("filledObserved"), t("settlement")], list(observation.orders).map(row => [code(row.client_id), code(row.symbol), esc(row.raw_status), amount(row.filled_observed), chip(t(row.settlement || "UNKNOWN"))]), t("noAccountOrders"))}
      ${orderEvidenceDetails(observation.order_evidence)}
      ${orderPageDetails(observation.order_pages)}
      <h3>${esc(t("accountExposure"))}</h3>${table([t("account"), t("product"), t("obligation"), t("status")], list(observation.exposure).map(row => [code(row.account_id), esc(row.raw_product || row.product), `${amount(row.obligation)} ${code(row.obligation_asset)}`, esc(row.status)]), t("noExposure"))}`);
  } catch (_) { summary.textContent = t("accountError"); setHTML("account-observations", ""); throw new Error(t("requestError")); }
}
async function externalJournal() {
  try {
    const data = await api("/api/external-order-events");
    setHTML("external-order-events", `<p class="field-help">${esc(t("externalNote"))}</p>${table([t("time"), t("account"), t("clientId"), t("rawStatus"), t("settlement")], list(data.events).slice(-100).reverse().map(row => [esc(when(row.observed_at)), code(row.account_id), code(row.client_id), esc(row.raw_status), chip(t(row.settlement || "UNKNOWN"))]), t("externalEmpty"))}`);
  } catch (_) { setHTML("external-order-events", empty(t("externalReadError"))); throw new Error(t("requestError")); }
}
async function offlineReviews() {
  try {
    const data = await api("/api/offline-ticket-reviews");
    setHTML("offline-review-events", table([t("previewHash"), t("state"), t("funded_authority"), t("actions")], list(data.tickets).slice(-100).reverse().map(row => [code(row.preview_sha256), esc(row.state), esc(t(row.funded_authority === true ? "yes" : "no")), row.state === "PREVIEWED" ? `<button class="button button-small" data-review-key="${esc(row.preview_sha256)}" data-decision="ACKNOWLEDGE">${esc(t("acknowledgeOffline"))}</button> <button class="button button-small" data-review-key="${esc(row.preview_sha256)}" data-decision="REJECT">${esc(t("rejectOffline"))}</button>` : ""]), t("offlineReviewEmpty")));
  } catch (_) { setHTML("offline-review-events", empty(t("offlineReviewReadError"))); throw new Error(t("requestError")); }
}
async function operate() {
  try {
    const safety = await api("/api/automation-safety");
    if (safety.mode !== "DISARMED" || safety.funded_authority !== false || safety.autopilot_enabled !== false || safety.executor_state_verified !== false
      || safety.protection !== "UNAVAILABLE" || safety.venue_stops !== "NOT_CERTIFIED" || safety.entries_enabled !== false) throw new Error("unsupported authority status");
    const fields = ["mode", "protection", "venue_stops", "entries_enabled", "autopilot_enabled", "funded_authority", "executor_state_verified", "source"];
    const html = keyValues(fields.map(key => [t(key), typeof safety[key] === "boolean" ? esc(t(safety[key] ? "yes" : "no")) : label(safety[key])]));
    setHTML("protection-state", html); setHTML("safety-status", html);
    setHTML("overview-safety", keyValues(["protection", "venue_stops", "funded_authority"].map(key => [t(key), typeof safety[key] === "boolean" ? esc(t("no")) : label(safety[key])])));
  } catch (_) {
    for (const id of ["protection-state", "safety-status", "overview-safety"]) setHTML(id, empty(t("protectionUnavailable")));
    throw new Error(t("requestError"));
  }
}

const ticketFields = ["symbol", "side", "intent", "quantity", "bid", "ask", "worst_price", "fee_rate", "operator_quote_cap", "available_quote", "available_base", "minimum_quote", "observed_at", "expires_at", "snapshot_seq", "quote_age_ms"];
function renderTicketFields() {
  let values = {};
  try { values = JSON.parse($("offline-ticket").value || "{}"); } catch (_) { /* The JSON editor retains invalid text for correction. */ }
  if (!values || typeof values !== "object" || Array.isArray(values)) values = {};
  setHTML("ticket-fields", ticketFields.map(key => {
    const options = key === "side" ? ["BUY", "SELL"] : key === "intent" ? ["ENTRY", "EXIT"] : null;
    const value = values[key] ?? "";
    return `<label for="ticket-${key}">${esc(t(key))}${options
      ? `<select id="ticket-${key}" name="${key}" data-ticket-field="${key}"><option value="">${esc(t("none"))}</option>${options.map(option => `<option value="${option}"${value === option ? " selected" : ""}>${esc(t(option))}</option>`).join("")}</select>`
      : `<input class="input" id="ticket-${key}" name="${key}" data-ticket-field="${key}" value="${esc(value)}" dir="ltr" autocomplete="off" spellcheck="false"${["symbol", "observed_at", "expires_at"].includes(key) ? "" : ' inputmode="decimal"'}>`}</label>`;
  }).join(""));
}
let ticketRevision = 0;
let currentPreview = null;
function invalidateTicket() {
  ticketRevision++;
  currentPreview = null;
  $("offline-ticket").removeAttribute("aria-invalid");
  setHTML("ticket-output", `<p class="field-help">${esc(t("previewChanged"))}</p>`);
}
function editTicketField() {
  const payload = {};
  for (const field of $("ticket-fields").querySelectorAll("[data-ticket-field]")) {
    const key = field.dataset.ticketField, value = field.value;
    payload[key] = ["snapshot_seq", "quote_age_ms"].includes(key) && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : value;
  }
  $("offline-ticket").value = JSON.stringify(payload, null, 2);
  invalidateTicket();
}

function syntheticTicket() {
  const now = new Date();
  return { symbol: "BTCUSDT", side: "BUY", intent: "ENTRY", quantity: "0.01", bid: "100", ask: "101", worst_price: "103",
    fee_rate: "0.002", operator_quote_cap: "2", available_quote: "2", available_base: "0", minimum_quote: "1",
    observed_at: now.toISOString(), expires_at: new Date(now.getTime() + 30000).toISOString(), snapshot_seq: 1, quote_age_ms: 0 };
}
async function previewTicket() {
  const input = $("offline-ticket"), button = $("preview-ticket"), output = $("ticket-output");
  const raw = input.value, revision = ticketRevision;
  button.disabled = true; button.setAttribute("aria-busy", "true"); input.removeAttribute("aria-invalid");
  output.textContent = t("previewBusy"); rendered.delete("ticket-output");
  try {
    JSON.parse(raw);
    // Preserve duplicate fields so the backend's strict parser can reject ambiguity.
    const preview = await api("/api/dry-run/ticket", { method: "POST", body: raw });
    if (ticketRevision !== revision || input.value !== raw) return;
    if (preview.mode !== "DRY_RUN") throw new Error("unexpected preview response");
    currentPreview = preview;
    setHTML("ticket-output", `<div class="ticket-result"><h3>${esc(t("offlineTicketResult"))}</h3><p class="field-help">${esc(t("quoteFeeOnly"))}</p>${keyValues([
      [t("pair"), code(preview.symbol)], [t("quantity"), amount(preview.quantity)],
      [t("expectedGross"), amount(preview.estimated_gross_quote)], [t("worstGross"), amount(preview.worst_gross_quote)],
      [t("worstFee"), amount(preview.worst_fee_quote)], [t(preview.side === "SELL" ? "worstProceeds" : "worstSpend"), amount(preview.worst_total_quote)],
      [t("breakEven"), amount(preview.break_even_bid)], [t("effective"), `${esc(when(preview.observed_at))} → ${esc(when(preview.expires_at))}`],
    ])}<button type="button" class="button" id="save-preview">${esc(t("savePreview"))}</button>${disclosure(t("fullRecord"), preview, "ticket-preview")}</div>`);
  } catch (_) {
    if (ticketRevision !== revision || input.value !== raw) return;
    input.setAttribute("aria-invalid", "true");
    setHTML("ticket-output", `<p class="form-error" role="alert">${esc(t("offlineTicketError"))}</p>`);
  } finally { button.disabled = false; button.removeAttribute("aria-busy"); }
}

function renderRules(data) {
  $("rule-version").textContent = `${t("ruleVersion")} ${digits(data.version ?? "—")}`;
  const rules = list(data.rules), quarantined = list(data.quarantined);
  setHTML("rule-rows", (!rules.length && !quarantined.length ? `<section class="panel">${empty(t("rulesEmpty"), t("rulesEmptyHelp"))}</section>` : "")
    + rules.map(row => {
      const rule = row.body || {};
      return `<article class="panel rule-card"><div class="panel-heading"><div><h2 class="panel-title">${esc(rule.name || rule.id)}</h2><p class="field-help">${code(rule.id)} · ${code(rule.family)} · ${code(rule.action)}</p></div><div class="actions">${chip(t(row.state), row.state === "active" ? "ok" : "warn")}${row.state !== "disabled" ? `<button type="button" class="button button-small" data-disable="${esc(rule.id)}" data-focus="disable-${esc(rule.id)}"${state.savingRules ? " disabled" : ""}>${esc(t("disable"))}</button>` : ""}</div></div>
        ${rule.note ? `<p>${esc(rule.note)}</p>` : ""}${keyValues([[t("classification"), code(rule.class)], [t("status"), label(rule.status)], [t("source"), esc(rule.source)], [t("effective"), `${esc(when(rule.effective_from))} → ${rule.effective_until ? esc(when(rule.effective_until)) : "∞"}`], [t("blocksNow"), list(row.blocks_now).length ? row.blocks_now.map(code).join(", ") : esc(t("nothing"))]])}
        ${disclosure(t("history"), { rule, history: row.history || [] }, "rule-" + rule.id)}</article>`;
    }).join("") + quarantined.map(row => `<article class="panel rule-card"><div class="panel-heading"><h2 class="panel-title">${code(row.id)}</h2>${chip(t("quarantineNote"), "bad")}</div><p>${esc(row.error)}</p>${disclosure(t("fullRecord"), row.body || row, "quarantine-" + row.id)}</article>`).join(""));
}
async function rules() { state.rules = await api("/api/rules"); renderRules(state.rules); }
async function changeRule(button, action) {
  if (state.savingRules) return;
  state.savingRules = true; button.disabled = true; button.setAttribute("aria-busy", "true");
  try { await action(); await rules(); }
  catch (_) { $("rule-action-result").textContent = t("ruleWriteError"); }
  finally { state.savingRules = false; button.disabled = false; button.removeAttribute("aria-busy"); if (state.rules) renderRules(state.rules); }
}

function renderHealth(data) {
  setHTML("health-summary", stat(t("connected"), esc(t(data.connected ? "connectedValue" : "disconnectedValue")), t(data.demo ? "synthetic" : "liveData"))
    + stat(t("frameAge"), data.last_frame_age_s == null ? t("unknown") : `${num(data.last_frame_age_s)} <small>${esc(t("seconds"))}</small>`)
    + stat(t("reconnects"), num(data.reconnects)));
  const events = [...(data.fatal ? [data.fatal] : []), ...list(data.errors)];
  setHTML("health-errors", events.length ? `<ul class="event-list">${events.map(event => `<li>${typeof event === "string" ? esc(event) : json(event)}</li>`).join("")}</ul>` : empty(t("noCollectorEvents")));
  setHTML("health-quality", table([t("time"), t("instrument"), t("flag"), t("detail")], list(data.quality).map(row => [esc(when(row.ts)), code(row.instrument), label(row.flag), esc(row.detail)]), t("noQualityEvents")));
  const storage = data.storage, gib = bytes => bytes == null ? t("none") : digits((bytes / 2 ** 30).toFixed(1)) + " GiB";
  setHTML("health-storage", storage ? keyValues([[t("freeSpace"), esc(gib(storage.free_bytes))], [t("stopFloor"), esc(gib(storage.floor_bytes))],
    [t("growthPerHour"), esc(storage.growth_bytes_per_hour == null ? t("none") : digits((storage.growth_bytes_per_hour / 2 ** 20).toFixed(0)) + " MiB")],
    [t("hoursToFloor"), storage.hours_to_floor == null ? esc(t("none")) : `<span class="${storage.hours_to_floor < 48 ? "neg" : ""}">${num(storage.hours_to_floor)}</span>`],
    [t("lastArchive"), data.archived ? `${esc(when(data.archived.at))} · ${num(data.archived.days.length)}` : esc(t("none"))],
    [t("integritySweep"), data.integrity ? `${esc(when(data.integrity.at))} · ${num(data.integrity.checked)} ✓ · ${num(data.integrity.missing)} / ${num(data.integrity.mismatched)} ✗` : esc(t("none"))]])
    + table([t("shard"), t("markets"), t("status"), t("reconnects"), t("frameAge")], list(data.shards).map(row => [num(row.shard), num(row.markets),
      chip(t(row.connected ? "connectedValue" : "disconnectedValue"), row.connected ? "ok" : "bad"), num(row.reconnects), num(row.last_frame_age_s)]), t("noShards"), [0, 1, 3, 4])
    : empty(t("unavailable")));
  const readiness = data.readiness;
  setHTML("health-readiness", `<h2 class="panel-title">${esc(t("publicReadiness"))}</h2><p class="field-help">${esc(t("publicReadinessNote"))}</p><p>${label(readiness?.status)}</p>${table([t("pair"), t("status"), t("bidAge"), t("askAge")], list(readiness?.markets).map(row => [code(row.symbol), label(row.state), num(row.bid_age_seconds), num(row.ask_age_seconds)]), t("unavailable"))}`);
}
async function venueFacts() {
  try {
    const report = await api("/api/venue-facts");
    if (report.state === "NOT_CONFIGURED") { setHTML("venue-facts", empty(t("venueFactsEmpty"))); return; }
    setHTML("venue-facts", `<p class="field-help">${esc(t("venueFactsInfo"))}</p>${table([t("capability"), t("state")], Object.entries(report.capabilities || {}).map(([name, value]) => [esc(name), label(value.state)]))}
      ${table([t("time"), t("status"), t("source"), t("evidenceId")], list(report.facts).slice(0, 20).map(fact => [esc(when(fact.observed_at)), `${esc(fact.kind)} · ${esc(fact.state)}`, esc(fact.source), code(fact.evidence_id)]))}`);
  } catch (_) { setHTML("venue-facts", empty(t("venueFactsError"))); throw new Error(t("requestError")); }
}
async function chaos() {
  try {
    const report = await api("/api/chaos-report");
    if (report.state === "NOT_RUN") { setHTML("chaos-report", empty(t("chaosNotRun"))); return; }
    setHTML("chaos-report", `<p>${chip(t(report.passed === true ? "simulationPassed" : "simulationFailed"), report.passed === true ? "ok" : "bad")}</p><p class="field-help">${esc(t("chaosNote"))}</p>${table([t("fixture"), t("runs"), t("settled"), t("frozen"), t("violations")], list(report.fixtures).map(fixture => [esc(fixture.fixture), num(fixture.runs), num(fixture.settled), num(fixture.frozen), num(fixture.violations)]))}
      ${disclosure(t("exampleTrace"), { seeds_per_fixture: report.seeds_per_fixture, total_violations: report.total_violations, funded_authority: report.funded_authority, examples: list(report.fixtures).map(fixture => ({ fixture: fixture.fixture, incidents: fixture.incidents, example: fixture.example })) }, "chaos-examples")}`);
  } catch (_) { setHTML("chaos-report", empty(t("chaosError"))); throw new Error(t("requestError")); }
}

