"use strict";
// Native comparison setup, coverage and scheduled paper controls.
function strategyFields(entry, prefix, values = {}, slot = '') {
  const names = { fast: "parameterFast", slow: "parameterSlow", lookback: "parameterLookback", entry_bps: "parameterEntry", confirmation: "parameterConfirmation", reference: "parameterReference", deviations: "parameterDeviations",
    risk_bps: "parameterRisk", allocation_bps: "parameterAllocation", max_spread_bps: "parameterMaxSpread", participation_bps: "parameterParticipation", stop_atr: "parameterStopAtr", reward_risk: "parameterRewardRisk", cooldown_bars: "parameterCooldown", max_holding_bars: "parameterMaxHolding", max_drawdown_bps: "parameterMaxDrawdown" };
  const fields = Object.entries(entry.parameters.properties).map(([key, spec]) => {
    const id = `${prefix}-${key}`, value = values[key] ?? spec.default;
    const attrs = `id="${id}" data-slot="${slot}" data-parameter="${esc(key)}" required dir="ltr"`;
    const input = spec.enum ? `<select ${attrs}>${spec.enum.map(option => `<option${option === value ? " selected" : ""}>${esc(option)}</option>`).join("")}</select>`
      : `<input class="input" ${attrs} type="${spec.type === "integer" ? "number" : "text"}" value="${esc(value)}" ${spec.type === "integer" ? `min="${spec.minimum}" max="${spec.maximum}" step="1"` : `pattern="[A-Z0-9]{2,24}" maxlength="24"`}>`;
    return {key, html: `<label for="${id}"><span>${esc(t(names[key] || key))}</span>${input}</label>`};
  });
  const shared = field => field.key === 'regime_gate' || field.key === 'entry_risk_bps' || field.key.startsWith('exit_') && field.key !== 'exit_lookback';
  return fields.filter(field => !shared(field)).map(field => field.html).join('') +
    `<details class="disclosure"><summary>${esc(t('sharedStrategyControls'))}</summary><div class="ticket-fields">${fields.filter(shared).map(field => field.html).join('')}</div><p class="field-help">${esc(t('sharedStrategyControlsNote'))}</p></details>` +
    (["trend-pullback", "adaptive-channel"].includes(entry.id) ? `<p class="field-help">${esc(t("compoundRiskNote"))}</p>` : "");
}
function renderCandidate(slot) {
  const entry = list(state.researchSetup?.strategies).find(item => item.id === $("candidate-" + slot).value);
  if (!entry) return;
  setHTML("candidate-" + slot + "-params", strategyFields(entry, `parameter-${slot}`, state.candidateParams[slot] || {}, slot));
}
function renderCoverage() {
  const data = state.researchSetup?.coverage;
  if (!data) return;
  setHTML("paper-coverage", `<p><strong>${esc(t("coverageTitle"))} · ${code(data.symbol)}</strong> ${esc(when(data.from))} → ${esc(when(data.to))}</p><p>${esc(t("recordedObservations"))}: ${num(data.observations)} · ${esc(t("coverageGaps"))}: ${num(data.gaps_over_120s)}</p><p>${esc(t("coverageNote"))}</p>`);
}
async function setupResearch(symbol = "") {
  $("comparison-fields").disabled = true;
  try {
    const setup = await api("/api/research" + (symbol ? "?symbol=" + encodeURIComponent(symbol) : ""));
    if (symbol && $("compare-symbol").value !== symbol) return;
    const initial = !state.researchSetup;
    state.researchSetup = setup;
    if (initial) {
      $("compare-resolution").innerHTML = list(setup.resolutions ?? FIXED_RESOLUTIONS).map(item => `<option>${esc(item)}</option>`).join("");
      $("compare-resolution").value = setup.defaults.resolution;
      $("compare-symbol").innerHTML = list(setup.symbols).map(item => `<option>${esc(item)}</option>`).join("");
      $("compare-symbol").value = setup.coverage.symbol;
      $("compare-fee").value = setup.defaults.fee_rate;
      for (const [index, slot] of ["first", "second"].entries()) {
        $("candidate-" + slot).innerHTML = list(setup.strategies).map(entry => `<option value="${esc(entry.id)}">${esc(entry.title)}</option>`).join("");
        $("candidate-" + slot).value = setup.strategies[index]?.id || setup.strategies[0]?.id || "";
        renderCandidate(slot);
      }
    }
    $("compare-cash").value = setup.coverage.symbol.endsWith("TMN") ? "300000000" : "1000";
    // Start after the first USDTTMN quote so TMN results get a USDT-equivalent valuation and can be ranked.
    const start = [setup.coverage.from, setup.coverage.valuation_from && new Date(Date.parse(setup.coverage.valuation_from) + 1000).toISOString()]
      .filter(Boolean).sort().pop();
    for (const [field, value] of [["from", start], ["to", setup.coverage.to]]) {
      $("compare-" + field).value = value ? new Date(value).toISOString().slice(0, 19) : "";
    }
    $("comparison-fields").disabled = !setup.coverage.observations;
    renderCoverage();
  } catch (_) {
    if (symbol && $("compare-symbol").value !== symbol) return;
    $("comparison-fields").disabled = true; $("paper-coverage").textContent = t("researchUnavailable");
  }
}
function invalidateComparison() {
  comparisonRevision += 1;
  const hadResult = state.comparison !== null || state.comparing;
  state.comparison = null;
  if (hadResult) setHTML("compare-result", empty(t("comparisonChanged")));
}
async function submitComparison(event, validation = false) {
  event.preventDefault();
  if (state.comparing || !state.researchSetup || $("comparison-fields").disabled || $("compare-form").reportValidity?.() === false) return;
  const revision = comparisonRevision;
  const inputSignature = () => JSON.stringify([[...$("compare-form").querySelectorAll("input, select")].map(input => input.type === "checkbox" ? input.checked : input.value), state.candidateParams]);
  const signature = inputSignature();
  const candidates = ["first", "second"].map(slot => {
    const strategy = $("candidate-" + slot).value;
    const entry = state.researchSetup.strategies.find(item => item.id === strategy);
    const params = Object.fromEntries(Object.entries(entry.parameters.properties).map(([key, spec]) => {
      const value = state.candidateParams[slot]?.[key] ?? spec.default;
      return [key, spec.type === "integer" ? Number(value) : value];
    }));
    return { strategy, params };
  });
  state.comparison = null; state.comparing = true; $("compare-submit").disabled = true; $("validate-submit").disabled = true; $("compare-submit").setAttribute("aria-busy", "true");
  setHTML("compare-result", empty(t("comparing"))); renderComparison();
  try {
    const folds = Number($("validation-folds").value);
    const payload = { symbol: $("compare-symbol").value,
      from: $("compare-from").value + "Z", to: $("compare-to").value + "Z", resolution: $("compare-resolution").value,
      cash: $("compare-cash").value, fee_rate: $("compare-fee").value, latency_ms: 500, candidates };
    if ($("compare-participation").value.trim()) payload.participation = $("compare-participation").value.trim();
    for (const [id, key] of [["compare-max-fraction", "max_fraction"], ["compare-vol-target", "vol_target"], ["compare-maker-fee", "maker_fee_rate"]])
      if ($(id).value.trim()) payload[key] = $(id).value.trim();
    if ($("compare-order-type").value === "limit") payload.order_type = "limit";
    if ($("compare-walk-depth").checked) payload.walk_depth = true;
    if ($("compare-carry").checked) payload.carry_remainder = true;
    if (validation) payload.folds = folds;
    const data = await api(validation ? "/api/validate" : "/api/compare", { method: "POST", body: JSON.stringify(payload) }, 130000);
    const expected = validation ? (folds === 1 ? "TEMPORAL_VALIDATION" : "MULTI_WINDOW_VALIDATION") : "COMPARE";
    if (data.mode !== expected) throw new Error("unexpected comparison response");
    if (revision === comparisonRevision && signature === inputSignature()) { state.comparison = data; renderComparison(); }
    else if (revision === comparisonRevision) invalidateComparison();
    await research();
  } catch (error) {
    if (revision === comparisonRevision && signature !== inputSignature()) invalidateComparison();
    else if (revision === comparisonRevision) setHTML("compare-result", empty(t("compareError"), error.detail || ""));
  }
  finally { state.comparing = false; $("compare-submit").disabled = false; $("validate-submit").disabled = false; $("compare-submit").removeAttribute("aria-busy"); renderComparison(); }
}

async function research() {
  if (!state.researchSetup) await setupResearch();
  // shortcut: the list grows to 200 runs; older runs are reached with the symbol filter.
  const query = new URLSearchParams({ limit: String(state.runCount) });
  if (state.runFilter) query.set("symbol", state.runFilter);
  state.runs = list(await api("/api/runs?" + query));
  $("run-more").hidden = state.runs.length < state.runCount || state.runCount >= 200;
  if (!state.savedComparison && !state.runs.some(run => run.run_id === state.selectedRun) && state.selectedRun !== state.pinnedRun) { state.selectedRun = state.runs[0]?.run_id || ""; state.record = null; }
  renderRunList();
  if (state.savedComparison) return;
  if (!state.selectedRun) {
    setHTML("run-detail", `<section class="panel">${empty(t("noRuns"), t("noRunsHelp"))}<div class="actions"><button type="button" class="button button-primary" data-goto-tab="compare">${esc(t("startCompare"))}</button></div><p class="field-help">${esc(t("demoRunHelp"))}</p><pre class="output mono" dir="ltr">uv run gymctl demo-seed\nuv run gymctl paper BTCTMN --demo</pre></section>`);
    return;
  }
  if (state.record?.run_id === state.selectedRun) { renderRun(state.record); return; }
  const id = state.selectedRun;
  setHTML("run-detail", empty(t("loading")));
  try {
    const record = await api("/api/runs/" + encodeURIComponent(id));
    if (state.selectedRun === id) { state.record = record; renderRun(record); }
  } catch (_) { if (state.selectedRun === id) setHTML("run-detail", empty(t("runReadError"))); throw new Error(t("requestError")); }
}

function renderResearchJobs(data) {
  const hypotheses = new Map(list(data.hypotheses).map(row => [row.id, row]));
  const jobs = list(data.jobs);
  $("research-tick").disabled = state.researchBusy || !jobs.some(job => job.enabled === true);
  setHTML("research-jobs", table([t("strategy"), t("symbol"), t("status"), t("nextResearchRun"), t("lastResearchRun"), t("researchRetry"), t("actions")], jobs.map(job => {
    const hypothesis = hypotheses.get(job.hypothesis_id), action = job.enabled ? "pause" : "resume";
    return [code(hypothesis?.strategy), code(hypothesis?.symbol), esc(t(job.enabled ? "researchEnabled" : "researchPaused")),
      esc(when(job.next_at)), job.last_report?.run_id ? `<button type="button" class="button button-small" data-run="${esc(job.last_report.run_id)}">${esc(t("inspectRun"))}</button>` : label(job.last_report?.error_code ?? job.last_report?.status), esc(when(job.last_report?.retry_at)),
      `<button type="button" class="button button-small" data-research-action="${action}" data-job="${esc(job.id)}" data-focus="research-${esc(job.id)}"${state.researchBusy ? " disabled" : ""}>${esc(t(action === "pause" ? "researchPause" : "researchResume"))}</button>`];
  }), t("noResearchJobs")));
  setHTML("research-alerts", table([t("time"), t("status"), t("researchRetry")], list(data.alerts).slice(0, 20).map(alert => [esc(when(alert.due_at)), label(alert.kind), esc(when(alert.retry_at))]), t("noResearchAlerts")));
}
async function researchJobs() {
  try {
    const data = await api("/api/research-state");
    state.researchState = data; renderResearchJobs(data);
  } catch (_) {
    state.researchState = null;
    $("research-tick").disabled = true;
    setHTML("research-jobs", empty(t("researchStateError")));
    throw new Error(t("requestError"));
  }
}
async function controlResearch(action, id = "") {
  if (state.researchBusy || !["tick", "pause", "resume"].includes(action)) return;
  state.researchBusy = true;
  if (state.researchState) renderResearchJobs(state.researchState);
  try {
    const path = action === "tick" ? "/api/research/tick" : `/api/research/jobs/${encodeURIComponent(id)}/${action}`;
    const result = await api(path, { method: "POST", body: "{}" }, 130000);
    setHTML("research-control-result", `<p>${esc(t("researchControlDone"))}</p>`);
    await researchJobs();
  } catch (_) { setHTML("research-control-result", empty(t("researchControlError"))); }
  finally { state.researchBusy = false; if (state.researchState) renderResearchJobs(state.researchState); }
}

