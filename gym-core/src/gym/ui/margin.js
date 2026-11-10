/* Public Wallex terms and local paper replay share the CLI research actions. */
window.gymMargin = (() => {
  let language, catalogue, preview, busy = false;
  const $ = id => document.getElementById(id);
  const inputIds = ['margin-market', 'margin-side', 'margin-collateral', 'margin-risk', 'margin-price', 'margin-stop', 'margin-target', 'margin-from', 'margin-to', 'margin-exit-fee', 'margin-holding'];
  function mount({api, esc, keyValues, table, amount, when, stamp = (v, d) => esc(when(v, d)), demo = false}) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next || busy) return;
    // A language change preserves the operator's exact decimal inputs and receipt.
    const saved = language ? Object.fromEntries(inputIds.map(id => [id, $(id).value])) : {};
    language = next;
    const fa = language === 'fa', text = (en, persian) => fa ? persian : en;
    const field = (id, title, attributes = '') => `<label for="${id}"><span>${title}</span><input id="${id}" class="input" dir="ltr" ${attributes}></label>`;
    $('margin-workbench').innerHTML = `<h2>${text(T.en.mgWallexMarginLongShortPaperPositions, T.fa.mgWallexMarginLongShortPaperPositions)}</h2>
      <p class="field-help">${text(T.en.mgLoadCurrentMarketCreditLimitsObtain, T.fa.mgLoadCurrentMarketCreditLimitsObtain)}</p>
      <button id="margin-load" type="button" class="button">${text(T.en.mgLoadCurrentMarginRules, T.fa.mgLoadCurrentMarginRules)}</button><div id="margin-rules"></div>
      <form id="margin-preview-form"><fieldset id="margin-preview-fields" disabled><legend>${text(T.en.mgVenuePreviewNoOrder, T.fa.mgVenuePreviewNoOrder)}</legend><div class="ticket-fields">
      <label for="margin-market"><span>${text(T.en.mgMarginMarket, T.fa.mgMarginMarket)}</span><select id="margin-market" dir="ltr"></select></label>
      <label for="margin-side"><span>${text(T.en.mgDirection, T.fa.mgDirection)}</span><select id="margin-side" dir="ltr"><option value="long">LONG</option><option value="short">SHORT</option></select></label>
      ${field('margin-collateral', text(T.en.mgCollateralQuoteCurrency, T.fa.mgCollateralQuoteCurrency), 'required type="text" inputmode="decimal"')}
      ${field('margin-risk', text(T.en.mgCreditRatioVenueGrid, T.fa.mgCreditRatioVenueGrid), 'required type="number"')}
      ${field('margin-price', text(T.en.mgEntryLimitPrice, T.fa.mgEntryLimitPrice), 'required type="text" inputmode="decimal"')}
      ${field('margin-stop', text(T.en.mgStopLossOptional, T.fa.mgStopLossOptional), 'type="text" inputmode="decimal"')}
      ${field('margin-target', text(T.en.mgTakeProfitOptional, T.fa.mgTakeProfitOptional), 'type="text" inputmode="decimal"')}
      </div><div class="actions"><button id="margin-observed-price" type="button" class="button">${text(T.en.mgUseObservedBidAsk, T.fa.mgUseObservedBidAsk)}</button>
      <button type="submit" class="button button-primary">${text(T.en.mgCheckCollateralAndPreview, T.fa.mgCheckCollateralAndPreview)}</button></div></fieldset></form><div id="margin-preview"></div>
      <form id="margin-replay-form"><fieldset id="margin-replay-fields" disabled><legend>${text(T.en.mgReplayObservedQuotesPaperOnly, T.fa.mgReplayObservedQuotesPaperOnly)}</legend><div class="ticket-fields">
      ${field('margin-from', text(T.en.mgFromUtcAfterPreviewReceipt, T.fa.mgFromUtcAfterPreviewReceipt), 'required type="datetime-local" step="1"')}
      ${field('margin-to', text(T.en.mgToUtcExclusive, T.fa.mgToUtcExclusive), 'required type="datetime-local" step="1"')}
      ${field('margin-exit-fee', text(T.en.mgAssumedExitFeeQuoteCurrencyDecimal, T.fa.mgAssumedExitFeeQuoteCurrencyDecimal), 'required type="text" inputmode="decimal"')}
      ${field('margin-holding', text(T.en.mgCloseAfterSecondsOptional, T.fa.mgCloseAfterSecondsOptional), 'type="number" min="1" step="1"')}
      </div><div class="actions"><button id="margin-cutoff" type="button" class="button">${text(T.en.mgUseCurrentCutoff, T.fa.mgUseCurrentCutoff)}</button><button type="submit" class="button button-primary">${text(T.en.mgReplayPaperPosition, T.fa.mgReplayPaperPosition)}</button></div></fieldset></form>
      <p id="margin-status" role="status"></p><div id="margin-result" aria-live="polite"></div>`;
    const call = (action, value) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, 130000);
    function receipt(value, kind) {
      if (value?.schema !== 'wallex-margin/1' || value.kind !== kind || !/^[0-9a-f]{16}$/.test(value.run_id || '')) throw new Error('invalid paper receipt');
      if (kind === 'MARKETS' && !Array.isArray(value.markets)) throw new Error('missing rules');
      if (kind === 'PREVIEW' && (!value.collateral_limits || !value.terms || !['collateral', 'loan', 'trade_fee', 'open_fee', 'extend_fee'].every(key => value.terms[key]?.currency && typeof value.terms[key]?.value === 'string'))) throw new Error('missing terms');
      return value;
    }
    const money = row => `${amount(row.value)} <bdi dir="ltr">${esc(row.currency)}</bdi>`;
    const raw = value => `<details><summary>${text(T.en.mgSavedReceiptAndLimitations, T.fa.mgSavedReceiptAndLimitations)}</summary><pre class="output" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre></details>`;
    function controls() {
      $('margin-load').disabled = busy || demo;
      $('margin-preview-fields').disabled = busy || !catalogue;
      $('margin-replay-fields').disabled = busy || !preview;
    }
    async function act(fn) {
      if (busy || demo) return;
      busy = true; controls(); $('margin-status').textContent = text(T.en.rsWorking, T.fa.rsWorking);
      try { await fn(); $('margin-status').textContent = text(T.en.rsRequestCompleted, T.fa.rsRequestCompleted); }
      catch { $('margin-status').textContent = text(T.en.mgRequestFailedRefreshMarketRulesAnd, T.fa.mgRequestFailedRefreshMarketRulesAnd); }
      finally { busy = false; controls(); if (document.documentElement.lang !== language) mount({api, esc, keyValues, table, amount, when, stamp, demo}); }
    }
    function renderRules() {
      if (!catalogue) return;
      $('margin-market').innerHTML = catalogue.markets.map(row => `<option>${esc(row.symbol)}</option>`).join('');
      $('margin-rules').innerHTML = `<p>${text(T.en.receiptReceived, T.fa.receiptReceived)} · ${stamp(catalogue.received_at)}</p><details><summary>${text(T.en.mgPerMarketRules, T.fa.mgPerMarketRules)} · ${catalogue.markets.length}</summary>` + table(
        [text(T.en.pair, T.fa.pair), text(T.en.mgMinimumCredit, T.fa.mgMinimumCredit), text(T.en.mgMaximumCredit, T.fa.mgMaximumCredit), text(T.en.mgStep, T.fa.mgStep), text(T.en.mgLiquidationMarginFraction, T.fa.mgLiquidationMarginFraction), text(T.en.mgMaxAgeSeconds, T.fa.mgMaxAgeSeconds)],
        catalogue.markets.map(row => [esc(row.symbol), amount(row.min_risk_coef), amount(row.max_risk_coef), amount(row.risk_coef_step), amount(row.liquidity_margin), esc(row.max_age)])) + '</details>';
    }
    function bounds() {
      const row = catalogue?.markets.find(row => row.symbol === $('margin-market').value);
      if (!row) return;
      for (const [name, value] of [['min', row.min_risk_coef], ['max', row.max_risk_coef], ['step', row.risk_coef_step]]) $('margin-risk').setAttribute(name, value);
      if (!$('margin-risk').value) $('margin-risk').value = row.min_risk_coef;
      $('margin-holding').max = row.max_age;
    }
    function renderPreview() {
      if (!preview) return;
      const terms = preview.terms;
      $('margin-preview').innerHTML = keyValues([
        [text(T.en.mgSavedPreview, T.fa.mgSavedPreview), esc(preview.run_id)],
        [text(T.en.mgCollateralRange, T.fa.mgCollateralRange), `${amount(preview.collateral_limits.min)} – ${amount(preview.collateral_limits.max)} ${esc(terms.collateral.currency)}`],
        [text(T.en.mgLoan, T.fa.mgLoan), money(terms.loan)], [text(T.en.mgOpeningFee, T.fa.mgOpeningFee), money(terms.open_fee)],
        [text(T.en.mgEntryTradingFee, T.fa.mgEntryTradingFee), money(terms.trade_fee)], [text(T.en.mgExtensionFee, T.fa.mgExtensionFee), money(terms.extend_fee)],
        [text(T.en.mgExtensionPeriodSeconds, T.fa.mgExtensionPeriodSeconds), esc(terms.extend_time)],
        [text(T.en.mgWarningPrice, T.fa.mgWarningPrice), amount(terms.call_price)], [text(T.en.mgLiquidationPrice, T.fa.mgLiquidationPrice), amount(terms.liquidity_price)],
        [text(T.en.mgMaxAgeSeconds, T.fa.mgMaxAgeSeconds), esc(terms.max_age)],
      ]) + raw(preview);
    }
    function invalidate() { preview = null; $('margin-preview').textContent = ''; $('margin-result').textContent = ''; controls(); }
    $('margin-load').onclick = () => act(async () => { invalidate(); catalogue = null; $('margin-rules').textContent = ''; catalogue = receipt(await call('margin-markets', null), 'MARKETS'); renderRules(); bounds(); });
    $('margin-market').onchange = () => { invalidate(); $('margin-risk').value = ''; bounds(); };
    $('margin-preview-form').oninput = invalidate;
    $('margin-observed-price').onclick = () => act(async () => {
      const data = await api('/api/markets');
      const row = data.markets.find(row => row.symbol === $('margin-market').value);
      if (!row?.qualified || row.book_age_s == null || row.book_age_s < 0 || row.book_age_s > 30) throw new Error('quote unavailable');
      invalidate(); $('margin-price').value = row[$('margin-side').value === 'long' ? 'ask' : 'bid'];
    });
    $('margin-preview-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      invalidate();
      const request = {market: $('margin-market').value, side: $('margin-side').value, collateral: $('margin-collateral').value, risk_coef: $('margin-risk').value, open_price: $('margin-price').value};
      for (const [id, key] of [['margin-stop', 'stop_loss'], ['margin-target', 'take_profit']]) if ($(id).value) request[key] = $(id).value;
      const response = await call('margin-preview', {catalogue_id: catalogue.run_id, request});
      if (response.kind === 'COLLATERAL_LIMITS') {
        const limits = receipt(response, 'COLLATERAL_LIMITS').collateral_limits;
        $('margin-preview').innerHTML = keyValues([[text(T.en.mgRequiredCollateralRange, T.fa.mgRequiredCollateralRange), `${amount(limits.min)} – ${amount(limits.max)} ${esc(limits.currency)}`]]);
        return;
      }
      preview = receipt(response, 'PREVIEW'); renderPreview();
      $('margin-from').value = new Date(Date.parse(preview.received_at) + 1000).toISOString().slice(0, 19);
      $('margin-holding').max = preview.terms.max_age;
    }); };
    $('margin-cutoff').onclick = () => { $('margin-to').value = new Date().toISOString().slice(0, 19); };
    $('margin-replay-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      const result = await call('margin-replay', {preview_id: preview.run_id, from: $('margin-from').value + 'Z', to: $('margin-to').value + 'Z', exit_fee_rate: $('margin-exit-fee').value, holding_seconds: $('margin-holding').value ? Number($('margin-holding').value) : null});
      const row = result.result;
      $('margin-result').innerHTML = keyValues([
        [text(T.en.mgPaperState, T.fa.mgPaperState), esc(row.state)], [text(T.en.mgCashQuote, T.fa.mgCashQuote), amount(row.cash_quote)],
        [text(T.en.mgBaseHoldings, T.fa.mgBaseHoldings), amount(row.base_units)], [text(T.en.mgQuoteDebt, T.fa.mgQuoteDebt), amount(row.debt_quote)],
        [text(T.en.mgBaseDebt, T.fa.mgBaseDebt), amount(row.debt_base)], [text(T.en.mgMarkedEquityQuote, T.fa.mgMarkedEquityQuote), amount(row.equity_quote)],
        [text(T.en.mgQuoteStatus, T.fa.mgQuoteStatus), esc(row.mark.status)],
      ]) + table([text(T.en.mgFeeCurrency, T.fa.mgFeeCurrency), text(T.en.mgRecognizedCosts, T.fa.mgRecognizedCosts)], Object.entries(row.fees_by_currency || {}).map(([currency, value]) => [esc(currency), amount(value)]))
        + table([text(T.en.mgTimeUtc, T.fa.mgTimeUtc), text(T.en.mgPaperEvent, T.fa.mgPaperEvent), text(T.en.mgObservedSidePrice, T.fa.mgObservedSidePrice)], row.events.map(row => [esc(row.at), esc(row.action), amount(row.price)])) + raw(result);
    }); };
    renderRules();
    for (const [id, value] of Object.entries(saved)) $(id).value = value;
    bounds(); renderPreview(); controls();
  }
  return {mount, catalogueId: () => catalogue?.run_id || null};
})();
