/* Advanced research uses the same bounded service actions as gymctl research. */
window.gymResearch = (() => {
  let language;
  const actions = {
    register: [T.en.rsRegisterHypothesis, T.fa.rsRegisterHypothesis, 'symbol, strategy, params'],
    'shadow-open': [T.en.rsOpenPaperShadow, T.fa.rsOpenPaperShadow, 'position_id, hypothesis_id, quote, gross_quantity, fee_rate'],
    'shadow-close': [T.en.rsClosePaperShadow, T.fa.rsClosePaperShadow, 'position_id, quote'],
    schedule: [T.en.rsScheduleHypothesis, T.fa.rsScheduleHypothesis, 'hypothesis_id, every_seconds, lookback_seconds, first_at, resolution, cash, fee_rate'],
    list: [T.en.rsResearchLedger, T.fa.rsResearchLedger, ''],
    review: [T.en.rsReviewSavedRuns, T.fa.rsReviewSavedRuns, 'run_ids'],
    'claim-check': [T.en.rsCheckNumericClaims, T.fa.rsCheckNumericClaims, 'claims'],
    'outcome-add': [T.en.rsRecordRunOutcome, T.fa.rsRecordRunOutcome, 'Run ID'],
    outcomes: [T.en.rsAvailableOutcomeMemory, T.fa.rsAvailableOutcomeMemory, ''],
    'final-register': [T.en.rsPreregisterFutureEvaluation, T.fa.rsPreregisterFutureEvaluation, 'symbol, strategy, params, selection_end, test_from, test_to, resolution, cash, fee_rate, cost_declaration (optional: trades_per_month, roundtrip_cost_bps, expected_gross_edge_bps)'],
    'final-status': [T.en.rsInspectEvaluation, T.fa.rsInspectEvaluation, 'Evaluation ID'],
    'final-run': [T.en.rsConsumeEvaluationOnce, T.fa.rsConsumeEvaluationOnce, 'Evaluation ID'],
    'observe-import': [T.en.rsImportObservationVintages, T.fa.rsImportObservationVintages, 'observations'],
    screen: [T.en.rsScreenSuppliedObservations, T.fa.rsScreenSuppliedObservations, 'source_id, series, kind, unit, as_of, descending, limit, max_age_seconds'],
    derived: [T.en.rsAlignedRatiosAndSpreads, T.fa.rsAlignedRatiosAndSpreads, 'left, right, operation, as_of, max_age_seconds, max_skew_seconds'],
    diagnostic: [T.en.rsEvaluateAccountingOrMarketModel, T.fa.rsEvaluateAccountingOrMarketModel, 'model, parameters'],
    technicals: [T.en.rsClosedBarTechnicalTimeframes, T.fa.rsClosedBarTechnicalTimeframes, 'symbol, from, to, resolutions'],
    spreads: [T.en.rsObservedSpreadReport, T.fa.rsObservedSpreadReport, 'symbol, from, to'],
    'trade-flow': [T.en.rsRecordedTradeFlow, T.fa.rsRecordedTradeFlow, 'symbol, from, to'],
    candles: [T.en.rsPointInTimeCandleCrosscheck, T.fa.rsPointInTimeCandleCrosscheck, 'symbol, from, to, as_of, tolerance_bps'],
    'market-screen': [T.en.rsRankRecordedMarkets, T.fa.rsRankRecordedMarkets, 'symbols, reference, quote_currency, from, to, resolution, metric'],
    rebalance: [T.en.rsPreviewTargetRebalance, T.fa.rsPreviewTargetRebalance, 'quote_currency, cash, reserved_cash, fee_rate, positions: [{symbol, held, reserved, target_weight, bid, ask, quantity_step, minimum_quote}]'],
    'execution-quality': [T.en.rsCompareSuppliedFills, T.fa.rsCompareSuppliedFills, 'run_id, observations: [{fill_id, order_ref, side, quantity, price, fee, fee_currency, filled_at, observed_at}]'],
    'experiment-run': [T.en.rsRunExperimentAndStressScenarios, T.fa.rsRunExperimentAndStressScenarios, 'hypothesis, symbol, strategy, trials: [params], windows: [{from, to}], resolution, cash, scenarios: [{fee_rate, latency_ms, outages: [{from, to}]}], final_evaluation_id (null or saved ID)'],
    'experiment-list': [T.en.rsExperimentRegistry, T.fa.rsExperimentRegistry, ''],
    'experiment-status': [T.en.rsInspectSavedExperimentOrNote, T.fa.rsInspectSavedExperimentOrNote, 'Saved registry ID'],
  };
  const idActions = new Set(['outcome-add', 'final-status', 'final-run', 'experiment-status', 'prospective-status', 'prospective-evaluate']);
  actions['premium-research'] = [T.en.rsAnalyzeTmnConversionPremium, T.fa.rsAnalyzeTmnConversionPremium, 'base, from, to, resolution, max_age_seconds, max_skew_seconds, fee_rate; descriptive, no executable arbitrage'];
  actions['combine-oos'] = [T.en.rsCombineMatchedHistoricalOosPaperCurves, T.fa.rsCombineMatchedHistoricalOosPaperCurves, 'run_ids (2..4 verified matched native prospective sessions), lookback (3..100), rebalance_cost_bps (or null); prior-only weights; no live allocation'];
  actions['strategy-retirement-screen'] = [T.en.rsAuditBaselineUnderperformanceBeforeReview, T.fa.rsAuditBaselineUnderperformanceBeforeReview, 'run_ids (3..100 verified matched live sessions), universe (same frozen markets); evidence-only, no catalog auto-hide'];
  actions['meta-label-eligibility'] = [T.en.rsCheckDeferredMetaLabelEvidenceThreshold, T.fa.rsCheckDeferredMetaLabelEvidenceThreshold, 'closed_trades (verified integer count; >=300 only research eligible, no model trained)'];
  actions['margin-pairs-replay'] = [T.en.rsSimulateAMatchedLongShortMargin, T.fa.rsSimulateAMatchedLongShortMargin, 'long_preview_id, short_preview_id, from, to, exit_fee_rate, holding_seconds, max_skew_seconds (0..120); public archived quotes only, USDT scorecard if both USDT and settled; never venue orders'];
  actions['lead-lag-research'] = [T.en.rsTestCausalLeadLagAlignment, T.fa.rsTestCausalLeadLagAlignment, 'primary, leader, from, to, resolution, max_age_seconds, max_skew_seconds, min_overlap; optional max_delay_bars (1..12), strictly earlier training-only lag choice; descriptive only'];
  actions['twap-preview'] = [T.en.rsPreviewPaperTwapChildFills, T.fa.rsPreviewPaperTwapChildFills, 'symbol, from, to, side (BUY/SELL), quantity, slices, participation, fee_rate, available_quote, available_base, max_delay_seconds; optional cost_models (dated impact_models/hourly_costs); paper-only'];
  actions['stop-preview'] = [T.en.rsPreviewPaperStopOrder, T.fa.rsPreviewPaperStopOrder, 'symbol, from (order time), to, side (BUY/SELL), quantity, stop_price, type (STOP_MARKET/STOP_LIMIT), limit_price (null for STOP_MARKET), fee_rate; paper-only'];
  actions['credit-packages'] = [T.en.rsReadCreditPackages, T.fa.rsReadCreditPackages, 'null; reads the public package list and saves a receipt'];
  actions['credit-replay'] = [T.en.rsReplayCreditPackage, T.fa.rsReplayCreditPackage, 'packages_id (receipt), package_id, symbol (quoted in the package currency), from, to, exposure (0..1 of the account), fee_rate; paper-only'];
  actions['execution-choice-preview'] = [T.en.rsCompareHistoricalImmediateVsTwapCosts, T.fa.rsCompareHistoricalImmediateVsTwapCosts, 'symbol, from, to, side, quantity, slices (2..100), participation, fee_rate, available_quote, available_base, max_delay_seconds; optional dated cost_models. Retrospective only; not live execution advice.'];
  actions['prospective-register'] = [T.en.rsFreezeFutureStrategyComparison, T.fa.rsFreezeFutureStrategyComparison, 'symbol, candidates: [{strategy, params}], selection_end, test_from, test_to, resolution, cash, fee_rate; window must be in future'];
  actions['prospective-status'] = [T.en.rsInspectFrozenComparison, T.fa.rsInspectFrozenComparison, 'Saved 64-character registry ID'];
  actions['prospective-evaluate'] = [T.en.rsConsumeFutureComparisonOnce, T.fa.rsConsumeFutureComparisonOnce, 'Saved 64-character registry ID; failures are consumed'];
  actions['market-products'] = [T.en.rsInspectObservedMarketProductsAndCredit, T.fa.rsInspectObservedMarketProductsAndCredit, 'margin_catalogue_id: null or saved public MARKETS receipt ID; stale terms cannot establish current availability'];
  actions['campaign-status'] = [T.en.rsInspectCampaignProgressAndVerifiedSamples, T.fa.rsInspectCampaignProgressAndVerifiedSamples, 'limit: 1..100; complete journal counts, bounded verified readiness/trade sample; process liveness remains separate'];
  actions['walk-forward'] = [T.en.rsExpandingWalkForwardSearch, T.fa.rsExpandingWalkForwardSearch, 'hypothesis, symbol, candidates: [{strategy, params}], windows: [{train_from, train_to, test_from, test_to}], final_from, resolution, cash, fee_rate, latency_ms, purge_bars'];
  actions['execution-calibration'] = [T.en.rsInspectExecutionAssumptionEvidence, T.fa.rsInspectExecutionAssumptionEvidence, 'symbol (null for all markets), from, to, max_age_seconds; public feed timing only, no automatic cost defaults'];
  actions['execution-model-calibrate'] = [T.en.rsFitCausalPublicImpactAndHourly, T.fa.rsFitCausalPublicImpactAndHourly, 'symbol, from, to; bounded historical public prints, quotes, and local read-only fee receipts; paper-only, opt in explicitly'];
  actions['robustness'] = [T.en.rsInspectSelectionAndPathRobustness, T.fa.rsInspectSelectionAndPathRobustness, 'run_ids, partitions (4/6/8/10), seed, simulations, mean_block_length, max_gap_seconds; comparable verified historical runs only'];
  actions['strategy-audit'] = [T.en.rsCheckCausalityAndWarmUp, T.fa.rsCheckCausalityAndWarmUp, 'symbol, strategy, params, from, to, resolution, cash, fee_rate, latency_ms, checkpoints: [time], history_starts: [time]'];
  actions['return-bootstrap'] = [T.en.rsExploreSavedReturnUncertainty, T.fa.rsExploreSavedReturnUncertainty, 'run_id, seed, simulations, mean_block_length, max_gap_seconds'];
  actions['fractional-sizing'] = [T.en.rsAnalyzeCappedFractionalKellySizing, T.fa.rsAnalyzeCappedFractionalKellySizing, 'evaluation_id (completed preregistered evaluation), fraction (0..0.5 multiplier), cap (0..0.25), seed, simulations (100..500), block_length (1..50); no allocation changes automatically'];
  actions['experiment-scorecard'] = [T.en.rsExperimentScorecardAndParameterHeatmap, T.fa.rsExperimentScorecardAndParameterHeatmap, 'experiment_id, shadow_run_ids: up to four matched native prospective session IDs, or []'];
  actions['job-interrupt'] = [T.en.rsReleaseAnInterruptedPaperAttempt, T.fa.rsReleaseAnInterruptedPaperAttempt, 'job_id, expected_due, expected_claim, reason (fences publication; does not terminate a process)'];
  actions['return-correlations'] = [T.en.rsCompareAlignedMarketReturns, T.fa.rsCompareAlignedMarketReturns, 'symbols: [market], quote_currency, from, to, resolution, min_overlap'];
  actions['registry-page'] = [T.en.rsBrowseARegistrySnapshot, T.fa.rsBrowseARegistrySnapshot, 'kind (null or event kind), parent (null or saved ID), after, through (null for first page), limit'];
  actions['annotation-add'] = [T.en.rsSaveReplayAnnotation, T.fa.rsSaveReplayAnnotation, 'run_id, outputs_digest, decision_index, request_id (32 hex characters), text'];
  actions['annotation-list'] = [T.en.rsReadReplayAnnotations, T.fa.rsReadReplayAnnotations, 'run_id, outputs_digest, after, through, limit'];
  actions['replay-checkpoint'] = [T.en.rsSaveVerifiedReplayCheckpoint, T.fa.rsSaveVerifiedReplayCheckpoint, 'run_id, quote_count'];
  actions['replay-resume'] = [T.en.rsResumeAndVerifySavedReplay, T.fa.rsResumeAndVerifySavedReplay, 'checkpoint_id'];
  actions['entry-lock-add'] = [T.en.rsRecordPaperEntryLock, T.fa.rsRecordPaperEntryLock, 'run_id, scope (PAIR/GLOBAL), reason (COOLDOWN/DRAWDOWN), duration_seconds, threshold_percent (null for cooldown)'];
  actions['entry-locks'] = [T.en.rsInspectPaperEntryLocks, T.fa.rsInspectPaperEntryLocks, ''];
  actions['conversion-report'] = [T.en.rsEvaluateModeledConversion, T.fa.rsEvaluateModeledConversion, 'instruction, fills, mark_price, observed_at (offline modeled fills only)'];
  actions['probe-stage'] = [T.en.rsStageOfflineProbeBudget, T.fa.rsStageOfflineProbeBudget, 'total_loss_limit, quote_asset, probe: {probe_id, kind, symbol, worst_case_total_loss, venue_minimum_quote} (no permission to trade)'];
  actions['external-import'] = [T.en.rsImportManualAccountObservations, T.fa.rsImportManualAccountObservations, 'account_id, observed_at, balances, orders, exposure (sanitized observations only; no credentials)'];
  actions['venue-fact-import'] = [T.en.rsImportSanitizedVenueEvidence, T.fa.rsImportSanitizedVenueEvidence, 'evidence_id, observed_at, source, kind, endpoint, state, account_scope, response_version, evidence_sha256'];
  actions['evidence-report'] = [T.en.rsInspectSavedEconomicEvidence, T.fa.rsInspectSavedEconomicEvidence, 'run_id'];
  actions['evidence-decision'] = [T.en.rsRecordOfflineEvidenceDecision, T.fa.rsRecordOfflineEvidenceDecision, 'run_id, claim (NONE/EXPERIMENTAL), cap (decimal string), currency (USDT/TMN), note; record only'];
  actions['depth-audit'] = [T.en.rsValidateSuppliedDepthSequence, T.fa.rsValidateSuppliedDepthSequence, 'source_id, as_of, max_age_seconds, max_levels, frames: [{kind, sequence, previous_sequence, event_at, observed_at, bids: [[price, quantity]], asks: [[price, quantity]]}]'];
  actions['unit-convert'] = [T.en.rsConvertExplicitObservationEpochs, T.fa.rsConvertExplicitObservationEpochs, 'value, factor (exact observation references), from_epoch, to_epoch, target_unit, as_of, max_age_seconds, max_skew_seconds'];
  actions['market-breadth'] = [T.en.rsCompareMarketGroupBreadth, T.fa.rsCompareMarketGroupBreadth, 'groups: [{name, symbols}], quote_currency, from, to, resolution'];
  actions['order-page-import'] = [T.en.rsImportObservedOrderPage, T.fa.rsImportObservedOrderPage, 'account_id, observed_at, kind (OPEN/HISTORY), page, per_page, payload (documented map of order arrays; origin and completeness remain unverified)'];
  const $ = id => document.getElementById(id);
  function mount(api, esc) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next) return;
    language = next;
    const fa = language === 'fa';
    workspace(api, esc, fa);
    $('research-workbench').innerHTML = `<h2>${fa ? T.fa.rsAdvancedResearchWorkbench : T.en.rsAdvancedResearchWorkbench}</h2><p class="field-help">${fa ? T.fa.rsLocalInputsAndPaperResultsNo : T.en.rsLocalInputsAndPaperResultsNo}</p><form id="research-action-form"><label for="research-action">${fa ? T.fa.rsWorkflow : T.en.rsWorkflow}</label><select id="research-action">${Object.entries(actions).map(([id, labels]) => `<option value="${id}">${esc(labels[fa ? 1 : 0])}</option>`).join('')}</select><label for="research-action-input">${fa ? T.fa.rsInputJsonOrSavedId : T.en.rsInputJsonOrSavedId}</label><textarea id="research-action-input" rows="5" dir="ltr" spellcheck="false" aria-describedby="research-action-fields"></textarea><p id="research-action-fields" class="field-help" dir="ltr"></p><button class="button" type="submit">${fa ? T.fa.rsRunWorkflow : T.en.rsRunWorkflow}</button></form><p id="research-action-status" role="status"></p><pre id="research-action-result" class="output" dir="ltr"></pre>`;
    $('research-action-input').className = 'input code';
    const groups = [
      [T.en.rsSchedulesAndRecovery, T.fa.rsSchedulesAndRecovery, /^(schedule|job-|campaign-status$|list$)/],
      [T.en.rsExperimentsAndReplay, T.fa.rsExperimentsAndReplay, /^(register$|review$|experiment-|registry-|annotation-|replay)/],
      [T.en.rsMarketsAndObservations, T.fa.rsMarketsAndObservations, /^(premium-|lead-lag-|technical|spreads$|trade-flow$|candles$|market-|depth-|unit-|derived$|screen$|observe-)/],
      [T.en.rsResearchEvidenceAndEvaluation, T.fa.rsResearchEvidenceAndEvaluation, /^(research-|prospective-|claim-check$|outcome|final-)/],
      [T.en.rsAccountAndExecutionDiagnostics, T.fa.rsAccountAndExecutionDiagnostics, /./],
    ];
    $('research-action').innerHTML = groups.map(([en, persian], index) => `<optgroup label="${esc(fa ? persian : en)}">${Object.entries(actions)
      .filter(([id]) => groups.findIndex(group => group[2].test(id)) === index)
      .map(([id, labels]) => `<option value="${id}">${esc(labels[fa ? 1 : 0])}</option>`).join('')}</optgroup>`).join('');
    function update() {
      const action = $('research-action').value;
      $('research-action-fields').textContent = actions[action][2];
      $('research-action-input').disabled = !actions[action][2];
      $('research-action-input').required = !!actions[action][2];
    }
    $('research-action').onchange = update; update();
    $('research-action-form').onsubmit = async event => {
      event.preventDefault();
      const submit = event.target.querySelector('button'); submit.disabled = true;
      $('research-action-status').textContent = fa ? T.fa.rsWorking : T.en.rsWorking;
      $('research-action-result').textContent = '';
      try {
        const action = $('research-action').value;
        const input = $('research-action-input').value;
        const value = !actions[action][2] ? null : idActions.has(action) ? input.trim() : JSON.parse(input);
        const result = await api('/api/research/action', { method: 'POST', body: JSON.stringify({ action, value }) }, 130000);
        $('research-action-result').textContent = JSON.stringify(result, null, 2);
        document.getElementById('experiment-scorecard')?.remove();
        if (action === 'experiment-scorecard') scorecard(result, esc, fa);
        $('research-action-status').textContent = fa ? T.fa.rsRequestCompleted : T.en.rsRequestCompleted;
      } catch { $('research-action-status').textContent = fa ? T.fa.rsResultWasNotDeliveredTheOperation : T.en.rsResultWasNotDeliveredTheOperation; }
      finally { submit.disabled = false; }
    };
  }
  function scorecard(report, esc, fa) {
    const text = (en, persian) => fa ? persian : en;
    const host = document.createElement('section'); host.id = 'experiment-scorecard'; host.className = 'panel';
    const definitions = report.definition;
    host.innerHTML = `<h3>${text(T.en.rsEveryRegisteredTrial, T.fa.rsEveryRegisteredTrial)}</h3><p>${esc(report.registered_trials)} ${text(T.en.rsParameterTrials, T.fa.rsParameterTrials)} · ${esc(report.registered_attempts)} ${text(T.en.rsAttemptsIncludingFailures, T.fa.rsAttemptsIncludingFailures)}</p>
      <div class="table-wrap" tabindex="0"><table class="data"><caption>${text(T.en.rsNetResultInQuoteCurrencyUnready, T.fa.rsNetResultInQuoteCurrencyUnready)}</caption><thead><tr><th>${text(T.en.rsWindowCost, T.fa.rsWindowCost)}</th>${definitions.trials.map((params, i) => `<th scope="col">${i + 1}<br><code>${esc(JSON.stringify(params))}</code></th>`).join('')}</tr></thead><tbody>${definitions.windows.flatMap((period, w) => definitions.scenarios.map((cost, s) => `<tr><th scope="row"><time dir="ltr">${esc(period.from)} → ${esc(period.to)}</time><br><code>${esc(JSON.stringify(cost))}</code></th>${definitions.trials.map((_, trial) => {
        const row = report.rows.find(r => r.trial === trial && r.window === w && r.scenario === s), run = row?.run;
        const valid = run?.ready && run.valuation.status === 'CURRENT' && run.net_quote != null;
        const tone = valid && Number(run.net_quote) !== 0 ? Number(run.net_quote) > 0 ? 'positive' : 'negative' : 'neutral';
        const capacity = row?.capacity ?? run?.capacity;
        const capacityLabel = capacity?.capacity_usdt != null
          ? `${text(T.en.rsModeledCapacity, T.fa.rsModeledCapacity)}: ${capacity.capacity_usdt} USDT`
          : `${text(T.en.rsCapacityUnavailable, T.fa.rsCapacityUnavailable)}: ${capacity?.reason ?? 'NO_VERIFIED_RUN'}`;
        return `<td class="heat-${tone}">${esc(run?.net_quote ?? row?.verification ?? row?.state ?? 'RESULT_PENDING')} ${esc(run?.quote ?? '')}<br>${esc(row?.verification ?? row?.state ?? '')}<br>${esc(run ? `${run.ready ? 'READY' : 'NOT_READY'} · ${run.valuation.status} · ${run.fills} fills` : row?.reason ?? '')}<br><small>${esc(capacityLabel)}</small></td>`;
      }).join('')}</tr>`)).join('')}</tbody></table></div><p class="field-help">${report.limits.map(esc).join(' ')}</p>
      <form id="scorecard-overlay-form"><fieldset><legend>${text(T.en.rsChooseTwoToFourRecordedPaths, T.fa.rsChooseTwoToFourRecordedPaths)}</legend></fieldset><button class="button" type="submit">${text(T.en.rsCompareSelectedPaths, T.fa.rsCompareSelectedPaths)}</button></form><p id="scorecard-overlay-status" role="status"></p><div id="scorecard-overlay"></div>`;
    $('research-action-result').before(host);
    const runs = [...new Map([...report.rows.filter(r => r.run).map(r => r.run), ...report.shadows].map(run => [run.run_id, run])).values()];
    host.querySelector('fieldset').insertAdjacentHTML('beforeend', runs.map(run => `<label class="check"><input type="checkbox" name="path" value="${esc(run.run_id)}">${esc(`${run.kind} · ${run.run_id} · ${run.valuation.status}`)}</label>`).join(''));
    $('scorecard-overlay-form').onsubmit = event => {
      event.preventDefault();
      const ids = [...host.querySelectorAll('input[name="path"]:checked')].map(input => input.value);
      if (ids.length < 2 || ids.length > 4) { $('scorecard-overlay-status').textContent = text(T.en.rsChooseTwoToFourPaths, T.fa.rsChooseTwoToFourPaths); return; }
      $('scorecard-overlay-status').textContent = text(T.en.rsRecordedTimesEachPathStartsAt, T.fa.rsRecordedTimesEachPathStartsAt);
      $('scorecard-overlay').innerHTML = overlayFigure(runs.filter(run => ids.includes(run.run_id)).map(run => ({name:`${run.kind} · ${run.run_id}`, curve:run.curve})));
    };
  }
  function workspace(api, esc, fa) {
    let host = $('research-workspace');
    if (!host) {
      host = document.createElement('section'); host.id = 'research-workspace'; host.className = 'panel';
      $('research-workbench').before(host);
    }
    const text = (en, persian) => fa ? persian : en;
    const resolutions = JSON.parse($('gym-config').textContent).resolutions || [];
    const prospectiveStrategies = [
      ['ema-trend', 'EMA trend'], ['sma-cross', 'SMA crossover'],
      ['sma-reversion', 'SMA reversion'], ['bollinger-reversion', 'Bollinger reversion'],
      ['ema-confirmed', 'EMA confirmed'], ['relative-momentum', 'Relative momentum'],
      ['rsi-rebound', 'RSI rebound'], ['macd-cross', 'MACD crossover'],
    ];
    const prospectiveOptions = (selected, optional = false) =>
      (optional ? '<option value="">' + text(T.en.rsNotSelected, T.fa.rsNotSelected) + '</option>' : '') +
      prospectiveStrategies.map(([id, label]) => '<option value="' + esc(id) + '"' +
        (selected === id ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
    host.innerHTML = `<h2>${text(T.en.rsResearchWorkspace, T.fa.rsResearchWorkspace)}</h2>
      <p>${text(T.en.rsRecordedObservationsAndPaperDecisionsSupplied, T.fa.rsRecordedObservationsAndPaperDecisionsSupplied)}</p>
      <details open><summary>${text(T.en.rsGuidedPaperResearch, T.fa.rsGuidedPaperResearch)}</summary>
        <p class="field-help">${text(T.en.rsRecordedQuotesOnlyAllOutcomesRemain, T.fa.rsRecordedQuotesOnlyAllOutcomesRemain)}</p>
        <form id="guided-research-form" class="ticket-fields">
          <label>${text(T.en.rsResearchModel, T.fa.rsResearchModel)}<select id="guided-model">
            <option value="premium-research">${text(T.en.rsTmnPremium, T.fa.rsTmnPremium)}</option><option value="lead-lag-research">${text(T.en.rsLeadLag, T.fa.rsLeadLag)}</option>
            <option value="twap-preview">${text(T.en.rsTwapChildPreview, T.fa.rsTwapChildPreview)}</option>
            <option value="execution-choice-preview">${text(T.en.rsImmediateVsTwapPaperCosts, T.fa.rsImmediateVsTwapPaperCosts)}</option></select></label>
          <label>${text(T.en.rsPrimarySymbolOrBasePremiumBtc, T.fa.rsPrimarySymbolOrBasePremiumBtc)}<input id="guided-symbol" required pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text(T.en.rsLeaderSymbolLagOnly, T.fa.rsLeaderSymbolLagOnly)}<input id="guided-leader" value="ETHUSDT" pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text(T.en.windowFrom, T.fa.windowFrom)}<input id="guided-from" type="datetime-local" required></label>
          <label>${text(T.en.rsToUtc, T.fa.rsToUtc)}<input id="guided-to" type="datetime-local" required></label>
          <label>${text(T.en.rsFixedBar, T.fa.rsFixedBar)}<select id="guided-resolution">${resolutions.filter(x => x !== 'session').map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
          <label>${text(T.en.rsMaxQuoteAgeSeconds, T.fa.rsMaxQuoteAgeSeconds)}<input id="guided-age" type="number" min="1" max="3600" value="120" required></label>
          <label>${text(T.en.rsMaxAlignmentSkewSeconds, T.fa.rsMaxAlignmentSkewSeconds)}<input id="guided-skew" type="number" min="0" max="3600" value="10" required></label>
          <label>${text(T.en.rsFeeFraction, T.fa.rsFeeFraction)}<input id="guided-fee" value="0.001" inputmode="decimal" required></label>
          <div id="guided-twap-fields" class="ticket-fields" hidden>
            <label>${text(T.en.side, T.fa.side)}<select id="guided-side"><option>BUY</option><option>SELL</option></select></label>
            <label>${text(T.en.rsBaseQuantity, T.fa.rsBaseQuantity)}<input id="guided-quantity" value="1" inputmode="decimal"></label>
            <label>${text(T.en.rsChildSlices, T.fa.rsChildSlices)}<input id="guided-slices" type="number" min="1" max="100" value="4"></label>
            <label>${text(T.en.rsParticipation, T.fa.rsParticipation)}<input id="guided-participation" value="0.5" inputmode="decimal"></label>
            <label>${text(T.en.rsAvailableQuote, T.fa.rsAvailableQuote)}<input id="guided-cash" value="1000" inputmode="decimal"></label>
            <label>${text(T.en.rsAvailableBase, T.fa.rsAvailableBase)}<input id="guided-base" value="0" inputmode="decimal"></label>
            <label>${text(T.en.rsMaxDelaySeconds, T.fa.rsMaxDelaySeconds)}<input id="guided-delay" type="number" min="0" max="3600" value="10"></label>
          </div>
          <button class="button" type="submit">${text(T.en.rsRunPaperDiagnostic, T.fa.rsRunPaperDiagnostic)}</button>
        </form>
        <div id="guided-result" role="status" aria-live="polite"></div>
      </details>
      <details><summary>${text(T.en.rsFrozenProspectiveComparisonPaperOnly, T.fa.rsFrozenProspectiveComparisonPaperOnly)}</summary>
        <p class="field-help">${text(T.en.rsFreezeTwoToFourStrategyConfigurations, T.fa.rsFreezeTwoToFourStrategyConfigurations)}</p>
        <form id="prospective-register-form" class="ticket-fields">
          <label>${text(T.en.rsMarketSymbol, T.fa.rsMarketSymbol)}<input id="prospective-symbol" pattern="[A-Z0-9]{2,24}" autocomplete="off" required dir="ltr" placeholder="BTCUSDT"></label>
          <label>${text(T.en.rsSelectionCutoffUtc, T.fa.rsSelectionCutoffUtc)}<input id="prospective-selection-end" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text(T.en.rsFutureEvaluationStartUtc, T.fa.rsFutureEvaluationStartUtc)}<input id="prospective-test-from" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text(T.en.rsEvaluationEndUtcExclusive, T.fa.rsEvaluationEndUtcExclusive)}<input id="prospective-test-to" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text(T.en.rsFixedCloseResolution, T.fa.rsFixedCloseResolution)}<select id="prospective-resolution" required dir="ltr">${resolutions.filter(x => x !== 'session').map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
          <label>${text(T.en.rsStartingQuoteCashExactDecimal, T.fa.rsStartingQuoteCashExactDecimal)}<input id="prospective-cash" value="1000" inputmode="decimal" required dir="ltr"></label>
          <label>${text(T.en.rsFeeFractionExactDecimal, T.fa.rsFeeFractionExactDecimal)}<input id="prospective-fee" value="0.001" inputmode="decimal" required dir="ltr"></label>
          <label>${text(T.en.rsCandidateA, T.fa.rsCandidateA)}<select id="prospective-strategy-first" required>${prospectiveOptions('ema-trend')}</select></label>
          <label>${text(T.en.rsCandidateB, T.fa.rsCandidateB)}<select id="prospective-strategy-second" required>${prospectiveOptions('sma-cross')}</select></label>
          <label>${text(T.en.rsCandidateCOptional, T.fa.rsCandidateCOptional)}<select id="prospective-strategy-third">${prospectiveOptions('', true)}</select></label>
          <label>${text(T.en.rsCandidateDOptional, T.fa.rsCandidateDOptional)}<select id="prospective-strategy-fourth">${prospectiveOptions('', true)}</select></label>
          <details><summary>${text(T.en.rsOptionalStrategyParameterOverridesJson, T.fa.rsOptionalStrategyParameterOverridesJson)}</summary>
            <p class="field-help">${text(T.en.rsLeaveBlankToFreezeNativeDefaults, T.fa.rsLeaveBlankToFreezeNativeDefaults)}</p>
            <label>${text(T.en.rsCandidateAParameters, T.fa.rsCandidateAParameters)}<textarea id="prospective-params-first" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text(T.en.rsCandidateBParameters, T.fa.rsCandidateBParameters)}<textarea id="prospective-params-second" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text(T.en.rsCandidateCParameters, T.fa.rsCandidateCParameters)}<textarea id="prospective-params-third" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text(T.en.rsCandidateDParameters, T.fa.rsCandidateDParameters)}<textarea id="prospective-params-fourth" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
          </details>
          <button class="button" type="submit">${text(T.en.rsFreezeFuturePaperComparison, T.fa.rsFreezeFuturePaperComparison)}</button>
        </form>
        <form id="prospective-evaluate-form" class="ticket-fields">
          <label>${text(T.en.rsFrozenRegistrationId64HexCharacters, T.fa.rsFrozenRegistrationId64HexCharacters)}<input id="prospective-id" pattern="[0-9a-f]{64}" maxlength="64" autocomplete="off" spellcheck="false" required dir="ltr"></label>
          <button id="prospective-inspect" type="button" class="button">${text(T.en.rsInspectSavedStatusReadOnly, T.fa.rsInspectSavedStatusReadOnly)}</button>
          <label class="check"><input id="prospective-ack" type="checkbox">${text(T.en.rsIUnderstandAnEvaluationAttemptIs, T.fa.rsIUnderstandAnEvaluationAttemptIs)}</label>
          <button type="submit" class="button">${text(T.en.rsConsumeOnePaperEvaluationNoOrders, T.fa.rsConsumeOnePaperEvaluationNoOrders)}</button>
        </form>
        <div id="prospective-result" role="status" aria-live="polite"></div>
      </details>
      <details open><summary>${text(T.en.rsCoverageTimeline, T.fa.rsCoverageTimeline)}</summary>
        <form id="coverage-form" class="ticket-fields">
          <label>${text(T.en.symbol, T.fa.symbol)}<input id="coverage-symbol" required pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text(T.en.windowFrom, T.fa.windowFrom)}<input id="coverage-from" type="datetime-local" required></label>
          <label>${text(T.en.rsToUtc, T.fa.rsToUtc)}<input id="coverage-to" type="datetime-local" required></label>
          <label>${text(T.en.rsResolution, T.fa.rsResolution)}<select id="coverage-resolution">${resolutions.map(value => `<option>${esc(value)}</option>`).join('')}</select></label>
          <button class="button" type="submit">${text(T.en.rsInspectCoverage, T.fa.rsInspectCoverage)}</button></form><div id="coverage-timeline"></div></details>
      <details><summary>${text(T.en.rsFailedJobsAndRecovery, T.fa.rsFailedJobsAndRecovery)}</summary>
        <button id="recovery-refresh" class="button" type="button">${text(T.en.rsLoadJobs, T.fa.rsLoadJobs)}</button>
        <label>${text(T.en.rsRecoveryReason, T.fa.rsRecoveryReason)}<input id="recovery-reason" maxlength="256"></label><div id="recovery-jobs"></div></details>
      <details><summary>${text(T.en.rsDecisionReplay, T.fa.rsDecisionReplay)}</summary><form id="replay-form">
        <label>${text(T.en.rsSavedRunId, T.fa.rsSavedRunId)}<input id="replay-run" required pattern="[0-9a-f]{16}" dir="ltr"></label>
        <button class="button" type="submit">${text(T.en.rsOpenReplay, T.fa.rsOpenReplay)}</button></form>
        <div class="actions"><button id="replay-previous" type="button" class="button" disabled>${text(T.en.rsPrevious, T.fa.rsPrevious)}</button><button id="replay-next" type="button" class="button" disabled>${text(T.en.rsNext, T.fa.rsNext)}</button></div><div id="replay-decision"></div></details>
      <p id="research-workspace-status" role="status"></p>`;
    const call = (action, value) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, 130000);
    async function act(button, fn) {
      button.disabled = true; $('research-workspace-status').textContent = text(T.en.rsWorking, T.fa.rsWorking);
      try { await fn(); if ($('research-workspace-status').textContent === text(T.en.rsWorking, T.fa.rsWorking)) $('research-workspace-status').textContent = text(T.en.rsRequestCompleted, T.fa.rsRequestCompleted); }
      catch { $('research-workspace-status').textContent = text(T.en.rsRequestFailedRefreshTheSavedState, T.fa.rsRequestFailedRefreshTheSavedState); }
      finally { button.disabled = button.id === 'replay-previous' ? offset === 0 : button.id === 'replay-next' ? offset + 1 >= total : false; }
    }
    const json = value => `<pre class="output" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
    $('guided-model').onchange = () => {
      const choice = $('guided-model').value === 'execution-choice-preview';
      const twap = $('guided-model').value === 'twap-preview' || choice;
      $('guided-twap-fields').hidden = !twap;
      $('guided-slices').min = choice ? '2' : '1';
      if (choice && Number($('guided-slices').value) < 2) $('guided-slices').value = '2';
      const hideLabel = (id, hidden) => {
        const label = $(id).closest?.('label');
        if (label) label.hidden = hidden;
      };
      hideLabel('guided-leader', $('guided-model').value !== 'lead-lag-research');
      hideLabel('guided-resolution', twap);
      hideLabel('guided-age', twap);
      hideLabel('guided-skew', twap);
    };
    $('guided-model').onchange();
    $('guided-research-form').onsubmit = event => { event.preventDefault(); act(event.target.querySelector('button'), async () => {
      const action = $('guided-model').value;
      const from = $('guided-from').value + ':00Z', to = $('guided-to').value + ':00Z';
      const common = {from, to};
      const value = action === 'premium-research'
        ? {...common, base: $('guided-symbol').value, resolution: $('guided-resolution').value,
           max_age_seconds: Number($('guided-age').value), max_skew_seconds: Number($('guided-skew').value), fee_rate: $('guided-fee').value}
        : action === 'lead-lag-research'
          ? {...common, primary: $('guided-symbol').value, leader: $('guided-leader').value,
             resolution: $('guided-resolution').value, max_age_seconds: Number($('guided-age').value),
             max_skew_seconds: Number($('guided-skew').value), min_overlap: 3}
          : {...common, symbol: $('guided-symbol').value, side: $('guided-side').value, quantity: $('guided-quantity').value,
             slices: Number($('guided-slices').value), participation: $('guided-participation').value,
             fee_rate: $('guided-fee').value, available_quote: $('guided-cash').value,
             available_base: $('guided-base').value, max_delay_seconds: Number($('guided-delay').value)};
      $('guided-result').textContent = '';
      const report = await call(action, value);
      const summary = action === 'premium-research' ? report.coverage : action === 'lead-lag-research'
        ? {status: report.status, overlap: report.overlap, correlation: report.correlation}
        : action === 'execution-choice-preview'
          ? {status: report.status, lowerHistoricalCost: report.retrospective_lower_cost,
             twapAdvantageBps: report.twap_advantage_bps, reason: report.reason}
          : {requested: report.requested_quantity, filled: report.filled_quantity, cancelled: report.cancelled_quantity, children: report.children.length};
      $('guided-result').innerHTML = `<p><strong>${text(T.en.rsPaperOnlyNoOrderSubmitted, T.fa.rsPaperOnlyNoOrderSubmitted)}</strong></p><p>${esc(JSON.stringify(summary))}</p><details><summary>${text(T.en.rsInspectExactEvidence, T.fa.rsInspectExactEvidence)}</summary>${json(report)}</details>`;
    }); };
    let prospectiveBusy = false;
    const prospectiveIdPattern = /^[0-9a-f]{64}$/;
    const prospectiveNumberPattern = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
    const prospectiveError = message => {
      $('prospective-result').textContent = message;
      $('research-workspace-status').textContent = message;
    };
    const prospectiveUtc = id => {
      const raw = $(id).value;
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) throw new Error(text(T.en.rsEnterValidUtcDates, T.fa.rsEnterValidUtcDates));
      const stamp = raw + ':00Z';
      if (!Number.isFinite(Date.parse(stamp))) throw new Error(text(T.en.rsInvalidUtcDate, T.fa.rsInvalidUtcDate));
      return stamp;
    };
    const prospectiveParams = id => {
      const raw = $(id).value.trim();
      if (!raw) return {};
      const params = JSON.parse(raw);
      if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error(text(T.en.rsParametersMustBeAJsonObject, T.fa.rsParametersMustBeAJsonObject));
      return params;
    };
    const prospectiveEvidence = value => '<details><summary>' +
      text(T.en.rsInspectExactSavedEvidence, T.fa.rsInspectExactSavedEvidence) + '</summary>' + json(value) + '</details>';
    const prospectiveShow = (action, result) => {
      if (action === 'prospective-register') {
        if (!prospectiveIdPattern.test(result.id || '')) throw new Error('Invalid registration receipt');
        $('prospective-id').value = result.id;
        $('prospective-result').innerHTML = '<p><strong>' +
          text(T.en.rsFrozenPaperOnlyNoFundedAuthority, T.fa.rsFrozenPaperOnlyNoFundedAuthority) +
          '</strong></p><p dir="ltr"><code>' + esc(result.id) + '</code></p>' + prospectiveEvidence(result);
      } else if (action === 'prospective-status') {
        const consumed = (result.events || []).some(event => event.kind === 'PROSPECTIVE_ATTEMPT');
        $('prospective-result').innerHTML = '<p><strong>' +
          (k => text(T.en[k], T.fa[k]))(consumed ? 'rsAttemptConsumed' : 'rsAttemptNotConsumed') +
          '</strong></p><p>' + esc(result.kind || 'UNKNOWN') + ' · ' + esc(result.id || '') +
          '</p>' + prospectiveEvidence(result);
      } else {
        const report = result.report || {};
        const candidates = report.configuration?.candidates || [];
        const rows = Array.isArray(report.rows) ? report.rows : [];
        const headings = [text(T.en.rsCandidate, T.fa.rsCandidate), text(T.en.rsFills, T.fa.rsFills),
          text(T.en.rsNetInQuoteCurrency, T.fa.rsNetInQuoteCurrency), text(T.en.rsTradeCoverage, T.fa.rsTradeCoverage)];
        const body = rows.map((row, index) => {
          const net = row.net_available && row.net != null ? esc(String(row.net)) : text(T.en.rsUnavailable, T.fa.rsUnavailable);
          const trade = row.no_trade ? text(T.en.rsNoTrade, T.fa.rsNoTrade) : text(T.en.rsModeledTrades, T.fa.rsModeledTrades);
          const coverage = String(row.qualified ?? 'UNKNOWN') + '/' + String(row.observations ?? 'UNKNOWN');
          return '<tr><td>' + esc(candidates[index]?.strategy || row.config_hash || 'UNKNOWN') +
            '</td><td>' + esc(String(row.fills ?? 'UNKNOWN')) + '</td><td dir="ltr">' + net +
            '</td><td>' + trade + ' · ' + esc(coverage) + '</td></tr>';
        }).join('');
        $('prospective-result').innerHTML = '<p><strong>' +
          text(T.en.rsOneTimeAttemptRecordedPaperOnly, T.fa.rsOneTimeAttemptRecordedPaperOnly) +
          '</strong></p><p>' + (k => text(T.en[k], T.fa[k]))(report.comparable ? 'rsComparisonsAvailable' : 'rsComparisonsIncomplete') +
          '</p><div class="workspace-table"><table><thead><tr>' + headings.map(label => '<th>' + esc(label) + '</th>').join('') +
          '</tr></thead><tbody>' + body + '</tbody></table></div>' + prospectiveEvidence(result);
      }
    };
    const prospectiveCall = async (button, action, value) => {
      if (prospectiveBusy) return;
      prospectiveBusy = true; button.disabled = true;
      $('prospective-result').textContent = text(T.en.rsReadingOrSavingLocalPaperEvidence, T.fa.rsReadingOrSavingLocalPaperEvidence);
      try {
        const result = await call(action, value);
        prospectiveShow(action, result);
        $('research-workspace-status').textContent = text(T.en.rsPaperWorkflowCompleted, T.fa.rsPaperWorkflowCompleted);
      } catch (error) {
        // The shared API exposes bounded 4xx server validation text as error.detail,
        // not error.message. Do not display 5xx bodies or automatically retry.
        const detail = typeof error?.detail === 'string' && error.detail.trim()
          ? error.detail.slice(0, 240) : '';
        const guidance = action === 'prospective-evaluate'
          ? text(T.en.rsOutcomeNotConfirmedInspectTheSaved, T.fa.rsOutcomeNotConfirmedInspectTheSaved)
          : action === 'prospective-register'
            ? text(T.en.rsRegistrationWasNotConfirmedCorrectThe, T.fa.rsRegistrationWasNotConfirmedCorrectThe)
            : text(T.en.rsCouldNotReadRegistrationStatusVerify, T.fa.rsCouldNotReadRegistrationStatusVerify);
        prospectiveError(guidance + (detail ? ' · ' + detail : ''));
      } finally {
        prospectiveBusy = false; button.disabled = false;
      }
    };
    $('prospective-register-form').onsubmit = event => {
      event.preventDefault(); if (prospectiveBusy || event.target.reportValidity?.() === false) return;
      try {
        const selection_end = prospectiveUtc('prospective-selection-end');
        const test_from = prospectiveUtc('prospective-test-from');
        const test_to = prospectiveUtc('prospective-test-to');
        const selected = Date.parse(selection_end), from = Date.parse(test_from), to = Date.parse(test_to);
        if (!(selected <= Date.now() && Date.now() < from && from < to && to - from <= 31 * 86400000))
          throw new Error(text(T.en.rsSelectionCutoffMustBePastEvaluation, T.fa.rsSelectionCutoffMustBePastEvaluation));
        const resolution = $('prospective-resolution').value;
        const units = /^([1-9][0-9]*)(min|h|day)$/.exec(resolution);
        const stepMs = units ? Number(units[1]) * {min: 60000, h: 3600000, day: 86400000}[units[2]] : NaN;
        if (!Number.isFinite(stepMs) || from - selected < stepMs || (to - from) / stepMs > 1440)
          throw new Error(text(T.en.rsPurgeAtLeastOneFixedBar, T.fa.rsPurgeAtLeastOneFixedBar));
        const cash = $('prospective-cash').value.trim(), fee_rate = $('prospective-fee').value.trim();
        if (!prospectiveNumberPattern.test(cash) || /^0(?:\.0+)?$/.test(cash) || !prospectiveNumberPattern.test(fee_rate))
          throw new Error(text(T.en.rsCashAndFeesMustBeNonnegative, T.fa.rsCashAndFeesMustBeNonnegative));
        const candidates = [];
        for (const slot of ['first', 'second', 'third', 'fourth']) {
          const strategy = $('prospective-strategy-' + slot).value;
          if (strategy) candidates.push({strategy, params: prospectiveParams('prospective-params-' + slot)});
        }
        if (candidates.length < 2 || candidates.length > 4 || new Set(candidates.map(c => JSON.stringify(c))).size !== candidates.length)
          throw new Error(text(T.en.rsSelectTwoToFourDistinctCandidate, T.fa.rsSelectTwoToFourDistinctCandidate));
        const symbol = $('prospective-symbol').value.trim();
        if (!/^[A-Z0-9]{2,24}$/.test(symbol)) throw new Error(text(T.en.rsEnterAValidUppercaseMarketSymbol, T.fa.rsEnterAValidUppercaseMarketSymbol));
        prospectiveCall(event.target.querySelector('button'), 'prospective-register',
          {symbol, candidates, selection_end, test_from, test_to, resolution, cash, fee_rate});
      } catch (error) { prospectiveError(error.message || text(T.en.rsInvalidRegistration, T.fa.rsInvalidRegistration)); }
    };
    const prospectiveSavedId = () => {
      const id = $('prospective-id').value.trim();
      if (!prospectiveIdPattern.test(id)) throw new Error(text(T.en.rsEnterASaved64CharacterRegistration, T.fa.rsEnterASaved64CharacterRegistration));
      return id;
    };
    $('prospective-inspect').onclick = event => {
      if (prospectiveBusy) return;
      try { prospectiveCall(event.target, 'prospective-status', prospectiveSavedId()); }
      catch (error) { prospectiveError(error.message); }
    };
    $('prospective-evaluate-form').onsubmit = event => {
      event.preventDefault();
      if (prospectiveBusy || event.target.reportValidity?.() === false) return;
      try {
        const id = prospectiveSavedId();
        if (!$('prospective-ack').checked) throw new Error(text(T.en.rsExplicitOneTimeEvaluationAcknowledgmentIs, T.fa.rsExplicitOneTimeEvaluationAcknowledgmentIs));
        $('prospective-ack').checked = false;
        prospectiveCall(event.target.querySelector('button[type="submit"]'), 'prospective-evaluate', id);
      } catch (error) { prospectiveError(error.message); }
    };
    $('coverage-form').onsubmit = event => { event.preventDefault(); act(event.target.querySelector('button'), async () => {
      const result = await call('coverage', {symbol: $('coverage-symbol').value, from: $('coverage-from').value + ':00Z', to: $('coverage-to').value + ':00Z', resolution: $('coverage-resolution').value});
      $('coverage-timeline').innerHTML = `<p>${esc(result.report_id)} · ${esc(JSON.stringify(result.counts))}</p><p>${esc(result.limitation)}</p><div class="workspace-table"><table><thead><tr>${['UTC', text(T.en.rsState, T.fa.rsState), text(T.en.rsQuotes, T.fa.rsQuotes), text(T.en.rsLateTrades, T.fa.rsLateTrades), text(T.en.rsQuoteAgeS, T.fa.rsQuoteAgeS), text(T.en.rsIndicators, T.fa.rsIndicators)].map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${result.buckets.map(row => `<tr><td dir="ltr">${esc(row.from)}</td><td>${esc(row.status)}</td><td>${esc(row.quotes)}</td><td>${esc(row.late_trade_receipts)}</td><td>${esc(row.last_known_qualified_quote_age_seconds ?? 'UNKNOWN')} ${row.quote_stale ? text(T.en.rsStale, T.fa.rsStale) : ''}</td><td><details><summary>${text(T.en.rsReadiness, T.fa.rsReadiness)}</summary>${json(row.indicator_readiness)}</details></td></tr>`).join('')}</tbody></table></div>`;
    }); };
    async function jobs() {
      const result = await call('list', null);
      $('recovery-jobs').innerHTML = result.jobs.map((job, i) => `<article class="panel"><p dir="ltr">${esc(job.id)}</p><p>${esc(job.next_at)} · ${esc(job.last_report?.status ?? 'WAITING')}</p><div class="actions"><button type="button" class="button" data-job-index="${i}" data-recover="RETRY" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text(T.en.rsAllowRetry, T.fa.rsAllowRetry)}</button><button type="button" class="button" data-job-index="${i}" data-recover="SKIP" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text(T.en.rsRecordSkipOfThisWindow, T.fa.rsRecordSkipOfThisWindow)}</button><button type="button" class="button" data-job-index="${i}" data-recover="CATCHUP" ${job.enabled ? '' : 'disabled'}>${text(T.en.rsRunUpTo10DueWindows, T.fa.rsRunUpTo10DueWindows)}</button></div></article>`).join('') || text(T.en.rsNoScheduledJobs, T.fa.rsNoScheduledJobs);
      $('recovery-jobs').querySelectorAll('article').forEach((panel, i) => {
        const report = result.jobs[i].last_report;
        if (report?.error_code) {
          const reason = document.createElement('p');
          reason.textContent = report.error_code === 'HYPOTHESIS_VERSION_UNAVAILABLE'
            ? text(T.en.rsThisJobRequiresAnUnavailableEngine, T.fa.rsThisJobRequiresAnUnavailableEngine)
            : report.message;
          panel.append(reason);
        }
        if (report?.status !== 'RUNNING') return;
        panel.insertAdjacentHTML('beforeend', json(report));
        const release = document.createElement('button');
        release.type = 'button'; release.className = 'button'; release.dataset.jobIndex = i; release.dataset.recover = 'INTERRUPT';
        release.textContent = text(T.en.rsReleaseThisAttemptDoesNotStop, T.fa.rsReleaseThisAttemptDoesNotStop);
        panel.append(release);
      });
      $('recovery-jobs').querySelectorAll('button').forEach(button => { button.onclick = () => act(button, async () => {
        const job = result.jobs[Number(button.dataset.jobIndex)], action = button.dataset.recover;
        const response = action === 'INTERRUPT'
          ? await call('job-interrupt', {job_id: job.id, expected_due: job.next_at, expected_claim: job.last_report.claim_id, reason: $('recovery-reason').value})
          : action === 'CATCHUP' ? await call('job-catch-up', {job_id: job.id, limit: 10}) : await call('job-recover', {job_id: job.id, expected_due: job.next_at, action, reason: $('recovery-reason').value});
        await jobs(); $('research-workspace-status').textContent = JSON.stringify(response);
      }); });
    }
    $('recovery-refresh').onclick = event => act(event.target, jobs);
    let offset = 0, runId = '', total = 0, replayBusy = false, feature = '', annotationPending = null;
    async function replay() {
      if (replayBusy) return;
      replayBusy = true;
      try {
      const linkedOpen = $('replay-feature')?.closest('details')?.open ?? false;
      const notesOpen = $('replay-annotation-form')?.closest('details')?.open ?? false;
      const start = Math.max(0, offset - 149);
      const result = await call('replay', {run_id: runId, offset: start, limit: offset - start + 1}); total = result.total;
      const row = result.decisions.at(-1);
      $('replay-decision').innerHTML = row ? `<p>${offset + 1} / ${total} · ${esc(row.known_at_decision.t)} · ${esc(row.known_at_decision.action)}</p><h3>${text(T.en.rsKnownAtDecision, T.fa.rsKnownAtDecision)}</h3><p>${esc((row.known_at_decision.reasons ?? []).join(' · '))}</p><p dir="ltr">${text(T.en.rsBidAsk, T.fa.rsBidAsk)}: ${esc(row.known_at_decision.bid ?? 'UNKNOWN')} / ${esc(row.known_at_decision.ask ?? 'UNKNOWN')} · ${esc(row.known_at_decision.quote_time ?? 'UNKNOWN')}</p><h3>${text(T.en.rsHoldingsBeforeDecision, T.fa.rsHoldingsBeforeDecision)}</h3><p>${esc(row.balance_status)}</p>${json(row.balances_before)}<details><summary>${text(T.en.rsIndicatorValuesAndReadiness, T.fa.rsIndicatorValuesAndReadiness)}</summary>${json(row.known_at_decision.feature_values)}</details><details><summary>${text(T.en.rsRecordedRules, T.fa.rsRecordedRules)}</summary>${json(row.known_at_decision.rules_known)}</details><details><summary>${text(T.en.rsBarAndReferenceObservations, T.fa.rsBarAndReferenceObservations)}</summary>${json({bar: row.known_at_decision.bar_known, context: row.known_at_decision.context_known, reference: row.known_at_decision.reference_known, skipped: row.known_at_decision.skipped})}</details><details><summary>${text(T.en.rsLaterModeledOrderOutcomeNotKnown, T.fa.rsLaterModeledOrderOutcomeNotKnown)}</summary>${json(row.subsequent_modeled_order)}</details>` : text(T.en.rsNoRecordedDecisions, T.fa.rsNoRecordedDecisions);
      $('replay-decision').insertAdjacentHTML('afterbegin', window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa));
      if (row) {
        const features = Object.keys(row.known_at_decision.feature_values ?? {}).filter(key => {
          const value = row.known_at_decision.feature_values[key];
          return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value));
        });
        if (!features.includes(feature)) feature = features[0] ?? '';
        $('replay-decision').insertAdjacentHTML('beforeend', `<details><summary>${text(T.en.rsLinkedEquityAndIndicatorPanes, T.fa.rsLinkedEquityAndIndicatorPanes)}</summary>${window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa, 'equity')}<label>${text(T.en.rsRecordedIndicator, T.fa.rsRecordedIndicator)}<select id="replay-feature">${features.map(key => `<option ${key === feature ? 'selected' : ''} value="${esc(key)}">${esc(key)}</option>`).join('')}</select></label><div id="replay-feature-chart"></div></details><details><summary>${text(T.en.rsOperatorAnnotationsSeparateFromDecisionEvidence, T.fa.rsOperatorAnnotationsSeparateFromDecisionEvidence)}</summary><form id="replay-annotation-form"><label>${text(T.en.rsNoteOnThisDecision, T.fa.rsNoteOnThisDecision)}<textarea id="replay-annotation-text" maxlength="2000" required></textarea></label><button class="button" type="submit">${text(T.en.rsSaveAnnotation, T.fa.rsSaveAnnotation)}</button></form><div id="replay-annotations"></div><button id="replay-annotations-more" class="button" type="button" disabled>${text(T.en.rsMoreAnnotations, T.fa.rsMoreAnnotations)}</button></details>`);
        const featureChart = () => { $('replay-feature-chart').innerHTML = feature ? window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa, feature) : text(T.en.rsNoNumericIndicatorTrace, T.fa.rsNoNumericIndicatorTrace); };
        $('replay-feature').onchange = event => { feature = event.target.value; featureChart(); }; featureChart();
        $('replay-feature').closest('details').open = linkedOpen;
        $('replay-annotation-form').closest('details').open = notesOpen;
        const identity = {run_id: result.run_id, outputs_digest: result.outputs_digest};
        let pageAfter = 0, pageThrough = null;
        async function notes() {
          const page = await call('annotation-list', {...identity, after: pageAfter, through: pageThrough, limit: 20});
          pageThrough = page.through; pageAfter = page.next_after;
          $('replay-annotations').insertAdjacentHTML('beforeend', page.events.map(note => `<article><button type="button" class="button" data-replay-index="${note.decision_index}">${esc(note.decision_at)}</button><p>${esc(note.text)}</p><small>${esc(note.recorded_at)} · ${esc(note.id)}</small></article>`).join(''));
          $('replay-annotations-more').disabled = pageAfter == null;
        }
        await notes();
        $('replay-annotations-more').onclick = async event => { await act(event.target, notes); event.target.disabled = pageAfter == null; };
        $('replay-annotation-form').onsubmit = event => {
          event.preventDefault();
          act(event.target.querySelector('button'), async () => {
            const value = {...identity, decision_index: row.index, text: $('replay-annotation-text').value};
            const source = JSON.stringify(value);
            if (annotationPending?.source !== source) annotationPending = {source, request_id: crypto.randomUUID().replaceAll('-', '')};
            await call('annotation-add', {...value, request_id: annotationPending.request_id});
            annotationPending = null; await replay();
          });
        };
      }
      $('replay-decision').onclick = event => {
        const point = event.target.closest('[data-replay-index]');
        if (point && !replayBusy) act($('replay-form').querySelector('button'), async () => { offset = Number(point.dataset.replayIndex); await replay(); });
      };
      $('replay-decision').onkeydown = event => {
        const point = event.target.closest('[data-replay-index]');
        if (replayBusy || !point || !['Enter', ' ', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        act($('replay-form').querySelector('button'), async () => {
          offset = Math.max(0, Math.min(total - 1, Number(point.dataset.replayIndex) + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0)));
          await replay(); $('replay-decision').querySelector(`[data-replay-index="${offset}"]`)?.focus();
        });
      };
      $('replay-previous').disabled = offset === 0; $('replay-next').disabled = offset + 1 >= total;
      } finally { replayBusy = false; }
    }
    $('replay-form').onsubmit = event => { event.preventDefault(); if (replayBusy) return; runId = $('replay-run').value; offset = 0; act(event.target.querySelector('button'), replay); };
    $('replay-previous').onclick = event => { if (!replayBusy) act(event.target, async () => { offset = Math.max(0, offset - 1); await replay(); event.target.disabled = offset === 0; }); };
    $('replay-next').onclick = event => { if (!replayBusy) act(event.target, async () => { offset = Math.min(total - 1, offset + 1); await replay(); event.target.disabled = offset + 1 >= total; }); };
  }
  return { mount };
})();
