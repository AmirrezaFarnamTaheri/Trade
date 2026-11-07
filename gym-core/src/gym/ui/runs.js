"use strict";
// Saved paper runs and matched comparisons: detail panels, trade ledger, CSV export and saved-run comparison.
// Loaded before app.js, which wires the events; helpers from app.js are called only at render time.
const GLOSSARY = ["glossSharpe", "glossPsr", "glossDeflated", "glossRange", "glossSortino", "glossCalmar", "glossProfitFactor", "glossExposure", "glossTurnover", "glossKelly", "glossBeta", "glossAvgCost"];
const pct = (value, tone = true) => value == null ? esc(t("none")) : `<bdi dir="ltr" class="${tone ? signed(value) : ""}">${num(rounded(value, 2))} %</bdi>`;
function performancePanel(perf, quote) {
  if (perf?.status !== "AVAILABLE") return "";
  const r = perf.returns || {}, tr = perf.trades || {};
  const rows = [[t("annualReturn"), perf.annualized_return_pct == null ? esc(t("needs30")) : pct(perf.annualized_return_pct)],
    [t("volatility"), percent(r.volatility, 3)], [t("sortino"), ratio(r.sortino_annualized)], [t("calmar"), ratio(perf.calmar)],
    [t("profitFactor"), ratio(tr.profit_factor)], [t("expectancy"), `${money(tr.expectancy)} ${code(quote)}`],
    [t("avgWin"), money(tr.average_win)], [t("avgLoss"), money(tr.average_loss)], [t("avgHolding"), ratio(tr.average_holding_hours, 1)],
    [t("losingStreak"), num(tr.longest_losing_streak)], [t("turnover"), `${num(rounded(tr.turnover, 2))}×`], [t("exposure"), percent(tr.exposure, 0)],
    ...(tr.kelly_fraction != null ? [[t("kelly"), percent(tr.kelly_fraction)]] : []), [t("openPosition"), amount(tr.open_position?.quantity)],
    [t("avgCostPnl"), money(tr.average_cost_realized_pnl)]];
  const boot = r.bootstrap_90, bench = perf.benchmark;
  if (boot) rows.push([t("sharpeRange"), `${ratio(boot.sharpe_per_period[0], 3)} … ${ratio(boot.sharpe_per_period[1], 3)}`],
    [t("returnRange"), `${percent(boot.total_return[0], 2)} … ${percent(boot.total_return[1], 2)}`]);
  if (bench) rows.push([`${t("beta")} ${bench.name}`, ratio(bench.beta)], [t("alphaPeriod"), percent(bench.alpha_per_period, 3)],
    [t("infoRatio"), ratio(bench.information_ratio_per_period, 3)], [t("correlation"), ratio(bench.correlation)]);
  const trades = list(perf.ledger).map(trade => [esc(when(trade.opened_at)), esc(when(trade.closed_at)), ratio(trade.holding_seconds / 3600, 1),
    money(trade.quantity, 8), money(trade.cost), money(trade.proceeds), `<span class="${signed(trade.pnl)}">${money(trade.pnl)}</span>`, percent(trade.return, 2)]);
  const heads = [t("opened"), t("closed"), t("holding"), t("quantity"), t("cost"), t("proceeds"), t("pnl"), t("tradeReturn")], numeric = [2, 3, 4, 5, 6, 7];
  return `<section class="panel"><h3 class="panel-title">${esc(t("perfTitle"))}</h3><div class="stats stats-4">${stat(t("totalReturn"), pct(perf.total_return_pct))}${stat(t("maxDrawdown"), pct(perf.max_drawdown_pct, false))}${stat(t("sharpePeriod"), ratio(r.sharpe_per_period, 3), `${t("psr")}: ${percent(r.probabilistic_sharpe)}`)}${stat(t("winRate"), percent(tr.win_rate, 0), `${digits(tr.closed_trades ?? 0)} ${t("closedTrades")}`)}</div>
    ${keyValues(rows)}<p class="field-help">${esc(t("perfNote"))}</p>
    <details class="disclosure" data-key="metric-glossary"><summary>${esc(t("glossaryTitle"))}</summary><ul class="glossary">${GLOSSARY.map(key => `<li>${esc(t(key))}</li>`).join("")}</ul></details></section>
    <section class="panel"><div class="panel-heading"><h3 class="panel-title">${esc(t("tradesTitle"))} <span class="muted">${esc(quote)}</span></h3>${trades.length ? `<button type="button" class="button button-small" data-csv="trades">${esc(t("downloadCsv"))}</button>` : ""}</div><div class="cards">${table(heads, trades.slice(0, 25), t("noTrades"), numeric)}</div>${trades.length > 25 ? `<details class="disclosure" data-key="trades-more"><summary>${esc(t("showMore"))} · ${digits(trades.length - 25)}</summary>${table(heads, trades.slice(25), "", numeric)}</details>` : ""}</section>`;
}
function valuationPanel(result) {
  const valuation = result.valuation;
  if (!valuation) return "";
  const curve = list(valuation.curve);
  return `<section class="panel"><h3>${esc(t("usdtValuation"))}</h3>${keyValues([
    [t("status"), `${label(valuation.start?.status)} → ${label(valuation.end?.status)}`],
    [t("source"), esc(valuation.basis)]])}
    ${valuation.pair && curve.length && curve.every(row => row.equity_usdt_eq != null)
      ? curveFigure({curve: curve.map(row => [row.at, row.equity_usdt_eq]), quote: "USDT equivalent"}) : ""}
    <p class="field-help">${esc(t("fxCurveNote"))}</p>
    ${table([t("time"), t("usdtEquivalent"), t("fxState"), t("fxAge")], curve.slice(-25).map(row =>
      [esc(when(row.at)), amount(row.equity_usdt_eq), label(row.fx?.status), num(row.fx?.age_seconds)]), t("noCurve"), [1, 3])}</section>`;
}
function renderRun(record) {
  if (!record) return;
  const result = record.result || {}, inputs = record.inputs || {}, end = result.end || {}, quote = result.quote || "";
  const entries = Object.entries(end.waterfall || {});
  const costs = entries.length ? keyValues(entries.map(([key, value]) => [t(key), `<span class="${signed(value)}">${amount(value)}</span>`])) : empty(t("noCost"));
  const baselines = Object.entries({ strategy: result, ...(record.baselines || {}) }).map(([name, baseline]) => [esc(name),
    baseline.end ? `${money(baseline.end.net)} ${code(quote)}` : `${esc(t("unavailable"))}<span class="sub">${esc(baseline.unavailable || "")}</span>`, money(baseline.end?.net_usdt_eq), num(baseline.fills)]);
  const ranking = record.ranking || {};
  const evidence = record.evidence;
  const orders = new Map(list(result.orders).map(order => [order.ref, order]));
  const decisions = list(result.decisions).slice(-100).reverse();
  const decisionRow = decision => { const order = orders.get(decision.order);
    return [esc(when(decision.t)), `<strong>${esc(decision.action)}</strong>`, esc(list(decision.reasons).join("; ")), order ? `${label(order.status)}${order.price ? ` · ${amount(order.price)}` : ""}${order.reason ? `<span class="sub">${esc(order.reason)}</span>` : ""}` : ""]; };
  const decisionHeads = [t("time"), t("decisionAction"), t("reasons"), t("status")];
  setHTML("run-detail", `<header class="run-heading"><div><h2>${code(result.symbol || inputs.symbol)} <span class="muted">${esc(result.strategy || "")}</span></h2><p class="field-help">${esc(when(inputs.from))} → ${esc(when(inputs.to))} · ${code(inputs.resolution)} · ${code(result.session?.state || record.mode || "PAPER")} · ${esc(inputs.store === "demo" ? t("synthetic") : t("paperOnly"))}</p></div>${chip(t("noCapital"))}</header>
    <div class="stats stats-4">${stat(t("equity"), `${money(end.equity)} <small>${esc(quote)}</small>`)}${stat(t("net"), `<span class="${signed(end.net)}">${money(end.net)}</span> <small>${esc(quote)}</small>`)}${stat(t("fills"), num(result.fills))}${stat(t("observations"), `${num(result.qualified)} <small>/ ${num(result.observations)}</small>`)}</div>
    <section class="panel"><h3 class="panel-title">${esc(t("equityCurve"))}</h3>${curveFigure(result)}${keyValues([[t("sampledDrawdown"), evidence?.sampled_drawdown?.status === "AVAILABLE" ? `${amount(evidence.sampled_drawdown.maximum_percent)} %` : esc(t("unavailable"))]])}<p class="field-help">${esc(t("drawdownNote"))}</p></section>
    ${valuationPanel(result)}${performancePanel(evidence?.performance, quote)}
    <section class="panel"><h3 class="panel-title">${esc(t("costWaterfall"))} <span class="muted">${esc(quote)}</span></h3>${waterfallFigure(entries, quote)}<h4>${esc(t("exactValues"))}</h4>${costs}<p class="field-help">${esc(t("updated"))} ${esc(when(end.mark_time))}</p></section>
    <section class="panel"><h3 class="panel-title">${esc(t("baselineTitle"))}</h3><p class="field-help">${esc(t("baselineNote"))}</p>${table([t("strategy"), `${t("net")} · ${quote}`, t("usdtEquivalent"), t("fills")], baselines, "", [1, 2, 3])}${record.fx ? keyValues([[t("fxLabel"), `${amount(record.fx.start)} → ${amount(record.fx.end)}`], [t("status"), `${label(record.fx.start_status)} → ${label(record.fx.end_status)}`], [t("source"), esc(record.fx.basis)]]) : ""}</section>
    <section class="panel"><h3 class="panel-title">${esc(t("rankingTitle"))}</h3><p class="field-help">${esc(t("rankingNote"))}</p>${table([t("rank"), t("strategy"), t("usdtEquivalent"), t("fills")], list(ranking.active).map(row => [num(row.rank), esc(row.name), money(row.net_usdt_eq), num(row.fills)]), t("noActiveRank"), [2, 3])}
      ${list(ranking.abstainers).length ? `<h4>${esc(t("abstainers"))}</h4>${table([t("strategy"), `${t("net")} · ${quote}`, t("usdtEquivalent")], ranking.abstainers.map(row => [esc(row.name), money(row.net_quote), money(row.net_usdt_eq)]), "", [1, 2])}` : ""}</section>
    <section class="panel"><h3 class="panel-title">${esc(t("evidenceTitle"))}</h3>${evidence ? `<p>${esc(evidence.primary_limitation)}</p>${keyValues([[t("roundTrips"), num(evidence.completed_round_trips)], [t("claimCeiling"), code(evidence.claim_ceiling)], [t("evidenceGate"), esc(t(evidence.gate_eligible === true ? "yes" : "no"))]])}` : `<p>${esc(t("noEvidence"))}</p>`}
      ${list(record.warnings || evidence?.warnings).length ? `<ul class="evidence-warnings">${list(record.warnings || evidence?.warnings).map(warning => `<li>${esc(warning)}</li>`).join("")}</ul>` : ""}
      <div class="actions"><button type="button" class="button" data-export-run="${esc(record.run_id)}">${esc(t("exportSummary"))}</button><button type="button" class="button" data-export-run="${esc(record.run_id)}" data-format="html">${esc(t("exportHtml"))}</button></div><p class="field-help">${esc(t("summaryNote"))}</p>
      ${disclosure(t("reportDetails"), { report: evidence || null, capital_decisions: record.capital_decisions || [] }, "economic-evidence")}${disclosure(t("runInputs"), { inputs, session: result.session, fx: record.fx, outputs_digest: record.outputs_digest }, "run-inputs")}</section>
    <section class="panel"><div class="panel-heading"><h3 class="panel-title">${esc(t("lastDecisions"))}</h3>${decisions.length ? `<button type="button" class="button button-small" data-csv="decisions">${esc(t("downloadCsv"))}</button>` : ""}</div><p class="field-help">${esc(t("decisionHelp"))}</p>${table(decisionHeads, decisions.slice(0, 15).map(decisionRow), t("noDecisions"))}${decisions.length > 15 ? `<details class="disclosure" data-key="decisions-more"><summary>${esc(t("showMore"))} · ${digits(decisions.length - 15)}</summary>${table(decisionHeads, decisions.slice(15).map(decisionRow))}</details>` : ""}${decisions.length ? disclosure(t("decisionLog"), decisions.map(decision => ({ ...decision, order: orders.get(decision.order) || null })), "decision-log") : ""}</section>`);
}
function renderComparison() {
  $("compare-submit").textContent = t(state.comparing ? "comparing" : "compareAction");
  const data = state.comparison;
  if (!data) return;
  if (["TEMPORAL_VALIDATION", "MULTI_WINDOW_VALIDATION"].includes(data.mode)) {
    const windowText = window => `${esc(when(window.from))} → ${esc(when(window.to))}`;
    const windows = data.mode === "MULTI_WINDOW_VALIDATION" ? list(data.folds) : [data];
    setHTML("compare-result", `<section class="ticket-result"><h3>${esc(t("validationTitle"))} · ${code(data.validation_id)}</h3>${keyValues([
      [t("status"), label(data.status)], [t("validationWindows"), num(windows.length)],
    ])}<p class="field-help">${esc(t("validationNote"))}</p>${table([t("validationWindow"), t("status"), t("selectionWindow"), t("holdoutWindow"), t("selectedCandidate")], windows.map((fold, index) => [num(index + 1), label(fold.status), windowText(fold.windows.selection), windowText(fold.windows.holdout), code(fold.selected?.strategy)]))}${table([t("strategy"), t("time"), t("net"), t("inspectRun")], list(data.runs).map(record => [code(record.inputs.strategy), esc(when(record.inputs.to)), money(record.result.end?.net), `<button type="button" class="button button-small" data-run="${esc(record.run_id)}">${esc(t("inspectRun"))}</button>`]))}${disclosure(t("runInputs"), { folds: windows, trial_count: data.trial_count, limitation: data.limitation }, "validation-inputs")}</section>`);
    return;
  }
  const quote = data.runs[0]?.result?.quote || "", selection = data.selection;
  const rows = list(data.runs).map(record => { const perf = data.performance?.[record.run_id] || {}, r = perf.returns || {};
    return [code(record.inputs.strategy), `<span class="${signed(record.result.end?.net)}">${money(record.result.end?.net)}</span>`, pct(perf.total_return_pct),
      pct(perf.max_drawdown_pct, false), ratio(r.sharpe_per_period, 3), percent(r.probabilistic_sharpe),
      `${num(record.result.fills)}${perf.trades?.win_rate != null ? `<span class="sub">${esc(t("winRate"))} ${percent(perf.trades.win_rate, 0)}</span>` : ""}`,
      `<button type="button" class="button button-small" data-run="${esc(record.run_id)}">${esc(t("inspectRun"))}</button>`]; });
  setHTML("compare-result", `<section class="ticket-result"><h3>${esc(t("compareTitle"))} · ${code(data.comparison_id)}</h3><p class="field-help">${esc(t("comparisonLimit"))}</p><div id="compare-overlay">${state.overlays.get(data.comparison_id) || ""}</div>${table([t("strategy"), `${t("net")} · ${quote}`, t("totalReturn"), t("maxDrawdown"), t("sharpePeriod"), t("psr"), t("fills"), t("inspectRun")], rows, "", [1, 2, 3, 4, 5, 6])}
    ${selection ? `<h4>${esc(t("selectionTitle"))}</h4>${keyValues([[t("bestCandidate"), code(selection.best)], [t("trials"), num(selection.trials)], [t("luckThreshold"), ratio(selection.luck_threshold_per_period, 3)], [t("deflatedSharpe"), percent(selection.deflated_sharpe)]])}<p class="field-help">${esc(t("selectionNote"))}</p>` : ""}
    <h4>${esc(t("rankingTitle"))}</h4>${table([t("rank"), t("strategy"), t("usdtEquivalent")], list(data.ranking?.active).map(row => [num(row.rank), esc(row.name), money(row.net_usdt_eq)]), t("noActiveRank"), [2])}${disclosure(t("runInputs"), { shared: data.shared_inputs, candidates: data.runs.map(record => ({ run_id: record.run_id, config_hash: record.inputs.config_hash, params: record.inputs.params })) }, "comparison-inputs")}</section>`);
  loadOverlay(data);
}

// Equity paths of a finished comparison, fetched once per comparison (results omit the curves).
async function loadOverlay(data) {
  if (state.overlays.has(data.comparison_id)) return;
  state.overlays.set(data.comparison_id, "");
  try {
    const records = await Promise.all(list(data.runs).map(record => api("/api/runs/" + encodeURIComponent(record.run_id))));
    state.overlays.set(data.comparison_id, overlayFigure(records.map(record => ({ name: record.inputs.strategy, curve: record.result.curve }))));
    if (state.comparison?.comparison_id === data.comparison_id && $("compare-overlay")) setHTML("compare-overlay", state.overlays.get(data.comparison_id));
  } catch (_) { state.overlays.delete(data.comparison_id); }
}
function renderSavedComparison(records) {
  state.savedComparison = true;
  const rows = records.map(record => { const perf = record.evidence?.performance || {}, r = perf.returns || {}, end = record.result?.end || {};
    return [`${code(record.inputs?.symbol)} <span class="sub">${esc(record.inputs?.strategy || "")}</span>`, `${esc(when(record.inputs?.from, true))} → ${esc(when(record.inputs?.to, true))}`,
      `<span class="${signed(end.net)}">${money(end.net)}</span> ${code(record.result?.quote)}`, pct(perf.total_return_pct), pct(perf.max_drawdown_pct, false),
      ratio(r.sharpe_per_period, 3), percent(r.probabilistic_sharpe), num(record.result?.fills),
      `<button type="button" class="button button-small" data-run="${esc(record.run_id)}">${esc(t("inspectRun"))}</button>`]; });
  setHTML("run-detail", `<section class="panel"><h2 class="panel-title">${esc(t("savedComparisonTitle"))}</h2><p class="field-help">${esc(t("savedComparisonNote"))}</p>
    ${overlayFigure(records.map(record => ({ name: `${record.inputs?.symbol} · ${record.inputs?.strategy}`, curve: record.result?.curve })))}
    ${table([t("strategy"), t("window"), t("net"), t("totalReturn"), t("maxDrawdown"), t("sharpePeriod"), t("psr"), t("fills"), t("inspectRun")], rows, "", [2, 3, 4, 5, 6, 7])}</section>`);
}
// Spreadsheet cells that start with =, +, - or @ run as formulas; quote them unless they are plain numbers.
const csvCell = value => {
  let text = value == null ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) text = "'" + text;
  return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
function exportCsv(kind, record) {
  const rows = kind === "trades"
    ? [["opened_at", "closed_at", "holding_seconds", "quantity", "cost", "proceeds", "pnl", "return", "average_cost_pnl"],
       ...list(record.evidence?.performance?.ledger).map(trade => [trade.opened_at, trade.closed_at, trade.holding_seconds, trade.quantity, trade.cost, trade.proceeds, trade.pnl, trade.return, trade.average_cost_pnl])]
    : [["time", "action", "reasons", "close", "bid", "ask", "order", "order_status", "fill_price", "fill_qty", "fee"],
       ...list(record.result?.decisions).map(decision => { const order = list(record.result?.orders).find(item => item.ref === decision.order) || {};
         return [decision.t, decision.action, list(decision.reasons).join("; "), decision.close, decision.bid, decision.ask, decision.order, order.status, order.price, order.qty, order.fee]; })];
  const url = URL.createObjectURL(new Blob(["\ufeff" + rows.map(row => row.map(csvCell).join(",")).join("\r\n")], { type: "text/csv" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: `${record.run_id}-${kind}.csv` });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderRunList() {
  $("compare-picked").hidden = state.pickedRuns.size < 2;
  $("compare-picked").textContent = `${t("comparePicked")} · ${digits(state.pickedRuns.size)}`;
  setHTML("run-list", state.runs.map(run => `<li class="run-item"><input type="checkbox" class="run-pick" data-pick="${esc(run.run_id)}" ${state.pickedRuns.has(run.run_id) ? "checked" : ""} aria-label="${esc(`${t("pickRun")} ${run.inputs?.symbol || ""} ${run.run_id}`)}"><button type="button" class="run-link" data-run="${esc(run.run_id)}" data-focus="run-${esc(run.run_id)}" aria-pressed="${run.run_id === state.selectedRun}"><strong>${code(run.inputs?.symbol || run.result?.symbol || run.run_id)}</strong><span>${esc(when(run.inputs?.from, true))}</span><span class="sub">${code(run.run_id)} · ${esc(t(run.inputs?.store === "demo" ? "synthetic" : "liveData"))}</span></button></li>`).join(""));
}
