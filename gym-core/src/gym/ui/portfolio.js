/* Shared cash replay uses native records, separately from independent comparisons. */
window.gymPortfolio = (() => {
  let language, setup, record, checkpoint, busy = false;
  const $ = id => document.getElementById(id);
  const inputs = ['portfolio-symbols', 'portfolio-from', 'portfolio-to', 'portfolio-resolution', 'portfolio-cash', 'portfolio-fee', 'portfolio-strategy', 'portfolio-params', 'portfolio-weighting', 'portfolio-lookback', 'portfolio-cap', 'portfolio-drawdown', 'portfolio-daily-loss', 'portfolio-buffer', 'portfolio-clock', 'portfolio-correlation', 'portfolio-group-cap', 'portfolio-rebalance', 'portfolio-threshold'];
  function mount({api, esc, table, keyValues, amount, when, stamp = (v, d) => esc(when(v, d)), curveFigure, strategyFields}) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (next === language || busy) return;
    const saved = language ? Object.fromEntries(inputs.map(id => [id, $(id).value])) : {};
    language = next;
    const fa = next === 'fa', text = (en, persian) => fa ? persian : en;
    const field = (id, title, attrs = '') => `<label for="${id}">${title}<input id="${id}" class="input" dir="ltr" ${attrs}></label>`;
    $('portfolio-workbench').innerHTML = `<h2>${text(T.en.pfSharedCashPortfolioReplay, T.fa.pfSharedCashPortfolioReplay)}</h2>
      <p class="field-help">${text(T.en.pfOneStrategy2500DistinctBase, T.fa.pfOneStrategy2500DistinctBase)}</p>
      <button id="portfolio-load" type="button" class="button">${text(T.en.pfLoadObservedMarketsAndSavedPortfolios, T.fa.pfLoadObservedMarketsAndSavedPortfolios)}</button>
      <form id="portfolio-form"><fieldset id="portfolio-fields" disabled><legend>${text(T.en.pfHistoricalReplayUtcAtMost31, T.fa.pfHistoricalReplayUtcAtMost31)}</legend><div class="ticket-fields">
      ${field('portfolio-symbols', text(T.en.pfMarketsCommaSeparatedSameQuoteCurrency, T.fa.pfMarketsCommaSeparatedSameQuoteCurrency), 'required list="portfolio-markets" autocomplete="off"')}<datalist id="portfolio-markets"></datalist>
      <div><p class="field-help">${text(T.en.pfUseTheWholeObservedQuoteUniverse, T.fa.pfUseTheWholeObservedQuoteUniverse)}</p><button id="portfolio-all-usdt" class="button" type="button">${text(T.en.pfAllUsdtMarkets, T.fa.pfAllUsdtMarkets)}</button> <button id="portfolio-all-tmn" class="button" type="button">${text(T.en.pfAllTmnMarkets, T.fa.pfAllTmnMarkets)}</button></div>
      ${field('portfolio-from', text(T.en.windowFrom, T.fa.windowFrom), 'required type="datetime-local" step="1"')}
      ${field('portfolio-to', text(T.en.pfToUtcExclusive, T.fa.pfToUtcExclusive), 'required type="datetime-local" step="1"')}
      <label for="portfolio-resolution">${text(T.en.pfDecisionClose, T.fa.pfDecisionClose)}<select id="portfolio-resolution" dir="ltr"></select></label>
      ${field('portfolio-cash', text(T.en.pfStartingSharedCashQuoteUnits, T.fa.pfStartingSharedCashQuoteUnits), 'required inputmode="decimal" value="1000"')}
      ${field('portfolio-fee', text(T.en.pfFeePerFillFraction, T.fa.pfFeePerFillFraction), 'required inputmode="decimal" value="0.001"')}
      <label for="portfolio-strategy">${text(T.en.strategy, T.fa.strategy)}<select id="portfolio-strategy" dir="ltr"></select></label>
      <div id="portfolio-strategy-fields" class="ticket-fields"></div><details class="disclosure"><summary>${text(T.en.pfAdvancedStrategyParameters, T.fa.pfAdvancedStrategyParameters)}</summary><label for="portfolio-params">${text(T.en.pfExactParametersJsonObject, T.fa.pfExactParametersJsonObject)}<textarea id="portfolio-params" class="input code" dir="ltr" rows="3" spellcheck="false" required>{}</textarea></label></details>
      </div><details class="disclosure"><summary>${text(T.en.pfAllocationAndPortfolioRisk, T.fa.pfAllocationAndPortfolioRisk)}</summary><div class="ticket-fields">
      <label for="portfolio-weighting">${text(T.en.pfEntryWeighting, T.fa.pfEntryWeighting)}<select id="portfolio-weighting"><option value="equal">${text(T.en.pfEqual, T.fa.pfEqual)}</option><option value="inverse-volatility">${text(T.en.pfInverseVolatility, T.fa.pfInverseVolatility)}</option><option value="risk-parity">${text(T.en.pfEqualRiskContribution, T.fa.pfEqualRiskContribution)}</option></select></label>
      ${field('portfolio-lookback', text(T.en.pfClosedReturnIntervals, T.fa.pfClosedReturnIntervals), 'type="number" min="3" max="500" value="20"')}
      ${field('portfolio-cap', text(T.en.pfMaximumWeightFraction, T.fa.pfMaximumWeightFraction), 'inputmode="decimal" value="1"')}
      ${field('portfolio-drawdown', text(T.en.pfDrawdownLimitFractionOptional, T.fa.pfDrawdownLimitFractionOptional), 'inputmode="decimal"')}
      ${field('portfolio-daily-loss', text(T.en.pfTehranDailyLossLimitFractionOptional, T.fa.pfTehranDailyLossLimitFractionOptional), 'inputmode="decimal"')}
      ${field('portfolio-buffer', text(T.en.pfCashBufferFraction, T.fa.pfCashBufferFraction), 'inputmode="decimal" value="0"')}
      ${field('portfolio-clock', text(T.en.pfTargetRefreshSeconds, T.fa.pfTargetRefreshSeconds), 'type="number" min="60" max="604800" value="60"')}
      ${field('portfolio-correlation', text(T.en.pfCorrelationThresholdOptional, T.fa.pfCorrelationThresholdOptional), 'inputmode="decimal"')}
      ${field('portfolio-group-cap', text(T.en.pfCorrelatedGroupWeightCapFraction, T.fa.pfCorrelatedGroupWeightCapFraction), 'inputmode="decimal" value="1"')}
      <label for="portfolio-rebalance">${text(T.en.pfRebalanceExistingHoldings, T.fa.pfRebalanceExistingHoldings)}<select id="portfolio-rebalance"><option value="false">${text(T.en.pfOffEntriesOnly, T.fa.pfOffEntriesOnly)}</option><option value="true">${text(T.en.pfOnModeledBuysAndSells, T.fa.pfOnModeledBuysAndSells)}</option></select></label>
      ${field('portfolio-threshold', text(T.en.pfMinimumRebalanceDriftEquityFraction, T.fa.pfMinimumRebalanceDriftEquityFraction), 'inputmode="decimal" value="0.01"')}
      </div><p class="field-help">${text(T.en.pfWeightsUseAlignedPastClosedReturns, T.fa.pfWeightsUseAlignedPastClosedReturns)}</p></details><p class="field-help">${text(T.en.pfMarketFills500MsLatencyPoint, T.fa.pfMarketFills500MsLatencyPoint)}</p><button id="portfolio-submit" class="button" type="submit">${text(T.en.pfRunSharedCashReplay, T.fa.pfRunSharedCashReplay)}</button></fieldset></form>
      <p id="portfolio-status" role="status" aria-live="polite"></p><div id="portfolio-saved"></div><div id="portfolio-result"></div><details class="disclosure"><summary>${text(T.en.pfVerifyReplayRecovery, T.fa.pfVerifyReplayRecovery)}</summary><p class="field-help">${text(T.en.pfRebuildAnExactSavedPortfolioPrefix, T.fa.pfRebuildAnExactSavedPortfolioPrefix)}</p>${field('portfolio-checkpoint-count', text(T.en.pfObservedQuotesInPrefix, T.fa.pfObservedQuotesInPrefix), 'type="number" min="1" max="100000" value="1"')}<div class="actions"><button id="portfolio-checkpoint" type="button" class="button">${text(T.en.pfSaveRecoveryCheckpoint, T.fa.pfSaveRecoveryCheckpoint)}</button><button id="portfolio-resume" type="button" class="button">${text(T.en.pfRebuildAndVerifyCheckpoint, T.fa.pfRebuildAndVerifyCheckpoint)}</button></div><p id="portfolio-recovery-status" role="status"></p></details>`;
    const call = (action, value = null) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, ['portfolio-replay','replay-checkpoint','replay-resume'].includes(action) ? 135000 : 10000);
    const controls = () => {
      $('portfolio-load').disabled = busy; $('portfolio-fields').disabled = busy || !setup;
      $('portfolio-checkpoint').disabled = busy || !record; $('portfolio-resume').disabled = busy || !checkpoint;
    };
    async function act(work) {
      if (busy) return;
      busy = true; controls(); $('portfolio-status').textContent = text(T.en.rsWorking, T.fa.rsWorking);
      try { if (await work() !== false) $('portfolio-status').textContent = text(T.en.rsRequestCompleted, T.fa.rsRequestCompleted); }
      catch { $('portfolio-status').textContent = text(T.en.pfRequestFailedCheckDistinctObservedMarkets, T.fa.pfRequestFailedCheckDistinctObservedMarkets); }
      finally { busy = false; controls(); if (document.documentElement.lang !== language) mount({api, esc, table, keyValues, amount, when, stamp, curveFigure, strategyFields}); }
    }
    function fillSetup() {
      if (!setup) return;
      $('portfolio-markets').innerHTML = setup.symbols.map(s => `<option value="${esc(s)}"></option>`).join('');
      $('portfolio-resolution').innerHTML = setup.resolutions.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
      $('portfolio-strategy').innerHTML = setup.strategies.map(s => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join('');
      $('portfolio-resolution').value = setup.defaults.resolution;
      $('portfolio-fee').value = setup.defaults.fee_rate;
      renderParameters();
    }
    function renderParameters() {
      const entry = setup?.strategies.find(row => row.id === $('portfolio-strategy').value);
      if (!entry?.parameters || !strategyFields) return;
      try { $('portfolio-strategy-fields').innerHTML = strategyFields(entry, 'portfolio-parameter', JSON.parse($('portfolio-params').value || '{}')); }
      catch { $('portfolio-status').textContent = text(T.en.pfCorrectTheAdvancedParameterJsonBefore, T.fa.pfCorrectTheAdvancedParameterJsonBefore); }
    }
    $('portfolio-strategy').onchange = () => { $('portfolio-params').value = '{}'; renderParameters(); };
    $('portfolio-params').onchange = renderParameters;
    $('portfolio-strategy-fields').oninput = event => {
      const key = event.target.dataset.parameter, entry = setup?.strategies.find(row => row.id === $('portfolio-strategy').value);
      const spec = entry?.parameters?.properties[key];
      if (!spec || busy) return;
      try {
        const params = JSON.parse($('portfolio-params').value || '{}');
        params[key] = spec.type === 'integer' ? Number(event.target.value) : event.target.value;
        $('portfolio-params').value = JSON.stringify(params);
      } catch { renderParameters(); }
    };
    async function savedRuns() {
      const data = await call('portfolio-list');
      $('portfolio-saved').innerHTML = `<p class="field-help">${text(T.en.pfSavedReferencesOpenARecordTo, T.fa.pfSavedReferencesOpenARecordTo)}</p>` + table([text(T.en.pfSavedPortfoliosLatest100, T.fa.pfSavedPortfoliosLatest100), text(T.en.strategy, T.fa.strategy), text(T.en.navMarkets, T.fa.navMarkets), text(T.en.pfWindowTehran, T.fa.pfWindowTehran)], data.runs.map(row => [
        `<button type="button" class="button button-small" data-portfolio="${esc(row.run_id)}">${esc(row.run_id)}</button>`, `${esc(row.inputs.strategy)} · ${esc(row.inputs.resolution)}`,
        `<details><summary>${esc(row.inputs.symbols.length)} · ${esc(row.inputs.symbols[0]?.endsWith('USDT') ? 'USDT' : 'TMN')}</summary><p dir="ltr">${esc(row.inputs.symbols.join(', '))}</p></details>`, `${stamp(row.inputs.from)} → ${stamp(row.inputs.to)}`]));
      $('portfolio-saved').querySelectorAll('[data-portfolio]').forEach(button => { button.onclick = () => act(async () => { record = await call('portfolio-read', {run_id: button.dataset.portfolio}); checkpoint = null; $('portfolio-recovery-status').textContent = ''; render(); }); });
    }
    function render() {
      if (!record) return;
      const result = record.result, end = result.end, valuation = result.valuation;
      const fxCurve = valuation?.curve || [];
      const conversion = valuation ? `<h4>${text(T.en.usdtValuation, T.fa.usdtValuation)}</h4>` + keyValues([
        [text(T.en.pfNetUsdtEquivalent, T.fa.pfNetUsdtEquivalent), end.net_usdt_eq == null ? text(T.en.pfUnavailable, T.fa.pfUnavailable) : amount(end.net_usdt_eq)],
        [text(T.en.pfStartEndFxStatus, T.fa.pfStartEndFxStatus), `${esc(valuation.start.status)} / ${esc(valuation.end.status)}`],
        [text(T.en.pfValuationBasis, T.fa.pfValuationBasis), esc(valuation.basis)]]) +
        (fxCurve.length && fxCurve.every(row => row.equity_usdt_eq != null) ? curveFigure({curve: fxCurve.map(row => [row.at, row.equity_usdt_eq]), quote: 'USDT equivalent'}) : '') +
        `<p class="field-help">${text(T.en.pfStaleAndStaleClosedUseAn, T.fa.pfStaleAndStaleClosedUseAn)}</p>` +
        table([text(T.en.pfLatest25ValuationMarksUtc, T.fa.pfLatest25ValuationMarksUtc), text(T.en.pfUsdtEquivalent, T.fa.pfUsdtEquivalent), text(T.en.fxState, T.fa.fxState), text(T.en.fxAge, T.fa.fxAge)],
          fxCurve.slice(-25).map(row => [stamp(row.at, false, 'UTC'), row.equity_usdt_eq == null ? text(T.en.pfUnavailable, T.fa.pfUnavailable) : amount(row.equity_usdt_eq), esc(row.fx.status), esc(row.fx.age_seconds ?? 'UNKNOWN')])) : '';
      $('portfolio-result').innerHTML = `<h3>${esc(record.run_id)} · ${esc(result.quote)}</h3>` + (result.policy_state ? keyValues([
        [text(T.en.pfPortfolioRiskLatch, T.fa.pfPortfolioRiskLatch), esc(result.policy_state.risk || 'CLEAR')],
        [text(T.en.pfAllocationReadiness, T.fa.pfAllocationReadiness), esc(result.policy_state.weights.status)],
        [text(T.en.pfPolicyScope, T.fa.pfPolicyScope), esc(result.policy_state.scope)]]) : '') + keyValues([
        [text(T.en.pfEquityRecordedBidMarks, T.fa.pfEquityRecordedBidMarks), amount(end.equity)], [text(T.en.pfNet, T.fa.pfNet), amount(end.net)],
        [text(T.en.pfHeldPriceFreshness, T.fa.pfHeldPriceFreshness), esc(end.valuation_status || 'UNKNOWN')],
        [text(T.en.pfRemainingCash, T.fa.pfRemainingCash), amount(result.balances?.[result.quote])],
        [text(T.en.pfReturn, T.fa.pfReturn), amount(record.performance?.total_return_pct)],
        [text(T.en.pfDrawdownSampled, T.fa.pfDrawdownSampled), amount(record.performance?.max_drawdown_pct)]]) + curveFigure(result) + table(
        [text(T.en.pair, T.fa.pair), text(T.en.pfFills, T.fa.pfFills), text(T.en.pfClosedTrades, T.fa.pfClosedTrades), text(T.en.pfRealizedPL, T.fa.pfRealizedPL), text(T.en.pfHeldBaseUnits, T.fa.pfHeldBaseUnits), text(T.en.pfLastRecordedBid, T.fa.pfLastRecordedBid), text(T.en.pfPriceFreshness, T.fa.pfPriceFreshness), text(T.en.pfLastMarkTehran, T.fa.pfLastMarkTehran)],
        Object.entries(result.markets).map(([s, row]) => [esc(s), esc(row.fills), esc(row.closed_trades), amount(row.realized_pnl), amount(row.holding), amount(row.last_bid), esc(row.mark_status || 'UNKNOWN'), stamp(row.mark_time)])) +
        conversion + `<details><summary>${text(T.en.pfVerifiedInputsOrdersAndExactBalances, T.fa.pfVerifiedInputsOrdersAndExactBalances)}</summary><pre class="output" dir="ltr">${esc(JSON.stringify(record, null, 2))}</pre></details>`;
    }
    $('portfolio-load').onclick = () => act(async () => {
      const data = await api('/api/research');
      if (!Array.isArray(data?.symbols) || !Array.isArray(data.resolutions) || !Array.isArray(data.strategies) || !data.defaults) throw new Error('Invalid research setup');
      if (data.portfolio_replay !== true) {
        setup = null;
        $('portfolio-status').textContent = text(T.en.pfTheRunningObservatoryNeedsARestart, T.fa.pfTheRunningObservatoryNeedsARestart);
        return false;
      }
      setup = data; fillSetup(); await savedRuns();
    });
    for (const quote of ['USDT', 'TMN']) $('portfolio-all-' + quote.toLowerCase()).onclick = () => {
      if (busy || !setup) return;
      $('portfolio-symbols').value = setup.symbols.filter(symbol => symbol.endsWith(quote)).join(', ');
      $('portfolio-status').textContent = text(T.en.pfAllObservedSelected, T.fa.pfAllObservedSelected).replaceAll('{quote}', quote);
    };
    $('portfolio-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      const policy = {method: $('portfolio-weighting').value || 'equal', lookback: Number($('portfolio-lookback').value || 20), max_weight: $('portfolio-cap').value || '1',
        cash_buffer: $('portfolio-buffer').value || '0', rebalance_seconds: Number($('portfolio-clock').value || 60), correlation_cap: $('portfolio-group-cap').value || '1',
        rebalance: $('portfolio-rebalance').value === 'true', rebalance_threshold: $('portfolio-threshold').value || '0.01'};
      for (const [id, key] of [['portfolio-drawdown', 'max_drawdown'], ['portfolio-daily-loss', 'daily_loss_limit']]) if ($(id).value) policy[key] = $(id).value;
      if ($('portfolio-correlation').value) policy.correlation_limit = $('portfolio-correlation').value;
      const result = await call('portfolio-replay', {symbols: $('portfolio-symbols').value.split(',').map(s => s.trim().toUpperCase()), policy,
        from: $('portfolio-from').value + 'Z', to: $('portfolio-to').value + 'Z', resolution: $('portfolio-resolution').value,
        cash: $('portfolio-cash').value, strategy: $('portfolio-strategy').value, params: JSON.parse($('portfolio-params').value),
        rules_mode: 'point-in-time', cost: {fee_rate: $('portfolio-fee').value, latency_ms: 500, max_wait_s: 60, fee_assumption: 'fee-in-received-asset'}});
      record = await call('portfolio-read', {run_id: result.run_id}); checkpoint = null; $('portfolio-recovery-status').textContent = ''; render(); await savedRuns();
    }); };
    fillSetup(); for (const [id, value] of Object.entries(saved)) $(id).value = value;
    $('portfolio-checkpoint').onclick = () => act(async () => {
      if (!record) throw new Error('Select a saved portfolio');
      checkpoint = (await call('replay-checkpoint', {run_id: record.run_id, quote_count: Number($('portfolio-checkpoint-count').value)})).record;
      $('portfolio-recovery-status').textContent = `${text(T.en.pfSavedCheckpoint, T.fa.pfSavedCheckpoint)}: ${checkpoint.run_id} · ${checkpoint.id}`;
    });
    $('portfolio-resume').onclick = () => act(async () => {
      if (!checkpoint) throw new Error('Save a checkpoint first');
      const result = await call('replay-resume', {checkpoint_id: checkpoint.id});
      $('portfolio-recovery-status').textContent = `${result.run_id} · ${result.status}`;
    });
    renderParameters();
    controls(); render();
  }
  return {mount};
})();
