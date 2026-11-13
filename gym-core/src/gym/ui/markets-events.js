$("market-filter").addEventListener("input", event => { state.filter = event.target.value; renderMarkets(); });
for (const id of ['market-quality', 'market-sort']) $(id).addEventListener('change', renderMarkets);
const venueProducts = venue => venue ? [venue.spot && 'SPOT', venue.margin && `MARGIN ≤${venue.max_leverage}×`, venue.otc && 'OTC', venue.zero_fee && 'ZERO_FEE'].filter(Boolean).map(code).join(' · ') : code('UNKNOWN');
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
$("market-rows").addEventListener("click", event => {
  const button = event.target.closest?.("[data-market]") || event.target;
  if (!button.dataset.market) return;
  state.expanded = state.expanded === button.dataset.market ? "" : button.dataset.market;
  renderMarkets();
});
