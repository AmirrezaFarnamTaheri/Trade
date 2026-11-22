$("market-filter").addEventListener("input", event => { state.filter = event.target.value; renderMarkets(); });
for (const id of ["market-quality", "market-sort"]) {
  const select = $(id);
  select.value = saved(id, select.value, [...select.options].map(option => option.value));
  select.addEventListener("change", () => { remember(id, select.value); renderMarkets(); });
}
const venueProducts = venue => {
  if (!venue) return code('UNKNOWN');
  const margin = venue.max_leverage == null ? 'MARGIN' : `MARGIN ≤${venue.max_leverage}×`;
  return [venue.spot === true && 'SPOT', venue.margin === true && margin,
    venue.otc === true && 'OTC', venue.zero_fee === true && 'ZERO_FEE'].filter(Boolean).map(code).join(' · ') || code('UNKNOWN');
};
$("products-refresh").onclick = async event => {
  const button = event.target; button.disabled = true;
  setHTML("product-capabilities", empty(t("loading")));
  try {
    const report = await api('/api/research/action', {method: 'POST', body: JSON.stringify({action: 'market-products', value: {margin_catalogue_id: window.gymMargin?.catalogueId() || null}})}, 130000);
    setHTML("product-capabilities", `<p class="field-help">${esc(report.scope)} · ${stampHtml(report.as_of)}</p>${table([t("pair"), t("entry"), t("exit"), t("status"), t("creditRatioGrid"), t("marginDirections"), t("venueProducts"), t("funded_authority")], list(report.markets).map(row => [code(row.symbol), code(row.spot.buy), code(row.spot.sell), code(row.margin.status), row.margin.credit_grid ? `${code(row.margin.credit_grid.minimum)} → ${code(row.margin.credit_grid.maximum)} · ${code(row.margin.credit_grid.step)}` : code(row.trade_credit), list(row.margin.directions).map(code).join(' / '), venueProducts(row.venue), code(row.funded_submission)]))}`);
  } catch (_) { setHTML("product-capabilities", empty(t("requestError"))); }
  finally { button.disabled = false; }
};
$("products-margin").onclick = async () => { await showView('research'); showResearchTab('margin', true); };
$("campaign-refresh").onclick = async event => {
  const button = event.target; button.disabled = true;
  setHTML('campaign-progress', empty(t('loading')));
  try {
    const report = await api('/api/research/action', {method:'POST', body:JSON.stringify({action:'campaign-status', value:{limit:25}})}, 130000);
    setHTML('campaign-progress', keyValues([[t('definedExperiments'), num(report.defined_experiments)], [t('registeredAttempts'), num(report.registered_attempts)], [t('COMPLETED'), num(report.completed)], [t('unreportedAttempts'), num(report.unreported_attempts)], [t('sampleReady'), num(report.verified_sample?.ready_runs)], [t('sampleTraded'), num(report.verified_sample?.traded_runs)], [t('sampleUnavailable'), num(report.verified_sample?.unavailable_runs)], [t('updated'), stampHtml(report.last_recorded_progress)]]) + `<p class="field-help">${esc(report.scope)}</p>${table([t('status'), t('runs')], Object.entries(report.terminal_states).map(([key, count]) => [label(key), num(count)]))}${table([t('processOwner'), t('status'), t('updated')], list(report.processes?.owners).map(row => [code(row.owner), code(row.state), stampHtml(row.heartbeat_at)]))}${table([t('pair'), t('strategy'), t('status'), t('ready'), t('fills'), t('net'), t('reason')], list(report.verified_sample?.rows).map(row => [code(row.symbol), code(row.strategy), code(row.verification || row.state), row.ready == null ? label('UNKNOWN') : label(row.ready ? 'READY' : 'NOT_READY'), num(row.fills), `${money(row.net_quote)} ${code(row.quote)}`, esc(row.reason || '')]))}`);
  } catch (_) { setHTML('campaign-progress', empty(t('requestError'))); }
  finally { button.disabled = false; }
};
$("quote-filter").addEventListener("click", event => {
  const button = event.target.closest?.("[data-quote]") || event.target;
  if (button.dataset.quote !== undefined) { state.quote = button.dataset.quote; renderMarkets(); }
});
$("market-rows").addEventListener("click", async event => {
  const qualBtn = event.target.closest?.("[data-quality-symbol]");
  if (qualBtn?.dataset.qualitySymbol) {
    const sym = qualBtn.dataset.qualitySymbol;
    const targetId = `quality-calendar-${sym}`;
    qualBtn.disabled = true;
    setHTML(targetId, empty(t("loading")));
    try {
      const [data, preflight, liq] = await Promise.all([
        api(`/api/quality-calendar?symbol=${encodeURIComponent(sym)}&days=14`),
        api(`/api/preflight?symbol=${encodeURIComponent(sym)}&days=14`),
        api(`/api/liquidity-profile?symbol=${encodeURIComponent(sym)}&days=14`),
      ]);
      const cal = data.calendar || {}, vintages = data.rule_vintages || {};
      const activeHours = list(liq.hours).filter(h => h.samples > 0);
      setHTML(targetId, `<h4>${esc(t("qualityCalendarTitle"))}</h4>${keyValues([
        [t("freshnessState"), label(cal.freshness_status || "UNKNOWN")],
        [t("ruleVintages"), num(vintages.vintage_count ?? 0)],
        [t("preflightStatus"), label(preflight.status || "UNKNOWN")],
      ])}${table([t("time"), t("completenessCol"), t("observedPairs"), t("attributionTrades")], list(cal.calendar).slice(-7).reverse().map(row => [
        code(row.date), label(row.completeness_status), num(row.quotes), num(row.trades),
      ]), t("nothing"))}<h4>${esc(t("liquidityTodTitle"))}</h4>${table([t("tehranHour"), t("sampleCount"), t("medianSpreadBps"), t("status")], activeHours.slice(0, 8).map(h => [
        code(String(h.tehran_hour).padStart(2, "0") + ":00"), num(h.samples), h.median_spread_bps == null ? esc(t("unknown")) : num(h.median_spread_bps), label(h.status),
      ]), t("nothing"))}`);
    } catch (_) { setHTML(targetId, empty(t("requestError"))); }
    finally { qualBtn.disabled = false; }
    return;
  }
  const button = event.target.closest?.("[data-market]") || event.target;
  if (!button.dataset.market) return;
  state.expanded = state.expanded === button.dataset.market ? "" : button.dataset.market;
  renderMarkets();
});
$("fx-route-form").addEventListener("submit", async event => {
  event.preventDefault();
  const btn = $("fx-route-submit");
  const direction = $("fx-route-direction").value;
  const amountText = $("fx-route-amount").value.trim();
  btn.disabled = true;
  setHTML("fx-route-output", empty(t("loading")));
  try {
    const data = await api(`/api/fx-route?direction=${encodeURIComponent(direction)}&amount=${encodeURIComponent(amountText)}`);
    const routes = list(data.routes);
    const best = routes[0], direct = data.direct_route ?? routes.find(row => row.legs === 1);
    const output = data.direction === "USDT_TO_TMN" ? "TMN" : "USDT";
    const input = output === "TMN" ? "USDT" : "TMN";
    const withUnit = (value, unit) => `${amount(value)} ${code(unit)}`;
    const priced = row => row && row.fits_displayed_size !== false;
    const displayed = direct && !routes.some(row => row.route === direct.route) ? [...routes, direct] : routes;
    setHTML("fx-route-output", keyValues([
      [t("status"), label(priced(best) ? "AVAILABLE" : "UNAVAILABLE")],
      [t("fxCheapestRoute"), priced(best) ? code(best.route) : esc(t("unavailable"))],
      [t("fxDirectRoute"), priced(direct) ? withUnit(direct.received, output) : esc(t("unavailable"))],
      [t("fxSavingBps"), data.saving_vs_direct_bps != null ? num(data.saving_vs_direct_bps) : esc(t("none"))],
      [t("fxFeePerLeg"), data.fee_per_leg != null ? num(Number(data.fee_per_leg) * 100) + "%" : esc(t("unknown"))],
      [t("depthScope"), label(data.depth_scope || "UNKNOWN")],
      [t("fxMaxQuoteAge"), data.max_quote_age_seconds != null ? num(data.max_quote_age_seconds) : esc(t("unknown"))],
    ]) + table([t("fxConversionRoute"), t("fxRouteCapacity"), t("fxRouteProceeds"), t("fxLegEvidence")],
      displayed.map(row => [
        code(row.route),
        row.capacity == null ? esc(t("unknown")) : withUnit(row.capacity, input),
        priced(row) ? withUnit(row.received, output) : esc(t("unavailable")),
        list(row.leg_details).map(leg => keyValues([
          [leg.symbol, label(leg.side)],
          [t("fxBidAsk"), `${amount(leg.bid)} / ${withUnit(leg.ask, leg.symbol.endsWith("TMN") ? "TMN" : "USDT")}`],
          [t("fxDisplayedBase"), withUnit(leg.displayed_base_quantity, leg.symbol.replace(/(?:TMN|USDT)$/, ""))],
          [t("spreadBps"), num(leg.spread_bps)],
          [t("fxQuoteReceived"), code(leg.quote_at)],
        ])).join("") || esc(t("unknown")),
      ]), t("nothing")));
  } catch (_) { setHTML("fx-route-output", empty(t("requestError"))); }
  finally { btn.disabled = false; }
});
$("size-preview-form").addEventListener("submit", async event => {
  event.preventDefault();
  const btn = $("size-preview-submit");
  const sym = $("size-preview-symbol").value.trim().toUpperCase();
  const side = $("size-preview-side").value;
  const qty = $("size-preview-qty").value.trim();
  btn.disabled = true;
  setHTML("size-preview-output", empty(t("loading")));
  try {
    const data = await api(`/api/size-preview?symbol=${encodeURIComponent(sym)}&side=${encodeURIComponent(side)}&qty=${encodeURIComponent(qty)}`);
    setHTML("size-preview-output", keyValues([
      [t("status"), label(data.status || "UNKNOWN")],
      [t("depthScope"), label(data.depth_scope || "UNKNOWN")],
      [t("filledQty"), amount(data.filled_qty)],
      [t("residualQty"), amount(data.residual_qty)],
      [t("vwapPrice"), data.vwap ? amount(data.vwap) : esc(t("unavailable"))],
    ]));
  } catch (_) { setHTML("size-preview-output", empty(t("requestError"))); }
  finally { btn.disabled = false; }
});
