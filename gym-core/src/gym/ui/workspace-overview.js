/** Switch the document language, direction, accessible labels, and live view translations. */
function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  document.documentElement.setAttribute("data-theme", theme);
  document.title = t("title");
  document.querySelectorAll("[data-t]").forEach(element => { element.textContent = t(element.dataset.t); });
  document.querySelectorAll("[data-t-placeholder]").forEach(element => { element.setAttribute("placeholder", t(element.dataset.tPlaceholder)); });
  document.querySelectorAll("[data-t-label]").forEach(element => { element.setAttribute("aria-label", t(element.dataset.tLabel)); });
  $("language-toggle").textContent = t("switchLanguage");
  $("language-toggle").setAttribute("lang", lang === "fa" ? "en" : "fa");
  $("theme-toggle").textContent = t(theme === "light" ? "darkTheme" : "lightTheme");
  $("zone-toggle").textContent = t(zone === "UTC" ? "zoneShowTehran" : "zoneShowUtc");
  $("zone-toggle").setAttribute("aria-label", `${t("zoneToggleLabel")}: ${t(zone === "UTC" ? "zoneShowTehran" : "zoneShowUtc")}`);
  $("current-view").textContent = t(viewKeys[state.view]);
  renderMarkets(); renderRunList();
  if (state.record) renderRun(state.record);
  else if (state.savedComparison) renderSavedComparison(state.savedComparison);
  if (state.health) renderHealth(state.health);
  if (state.rules) renderRules(state.rules);
  renderOverview(); renderTicketFields(); renderFeed(); updateClock();
  if (state.researchSetup) { for (const slot of ["first", "second"]) renderCandidate(slot); renderCoverage(); }
  renderComparison();
  if (state.researchState) renderResearchJobs(state.researchState);
  if (state.view === "research") mountResearchTab();
}

/** The governing question first: the tally of tested ideas, the forward paper record, then each idea's verdict. */
function renderAnswer() {
  const value = state.evidence;
  const failed = state.evidenceFailed;
  if (value?.state !== "READY") {
    return setHTML("overview-answer", empty(t(failed ? "answerFetchFailed" : value ? "answerNoLog" : "answerLoading")));
  }
  const stale = failed ? `<p class="field-help">${esc(t("answerStale"))} ${stampHtml(state.evidenceFetchedAt)}</p>` : "";
  const { tally, forward, trials } = value;
  const kinds = { PASS: "ok", NARROW_PASS: "warn", FAIL: "bad", OPEN: "neutral" };
  const verdicts = Object.keys(kinds);
  const selected = state.trialVerdict || "";
  const filtered = trials.filter(row => !selected || row.verdict === selected);
  const journals = forwardRecord(forward, trials.find(row => row.id === "btc-daily-trend"), kinds)
    + mixRecord(value.forward_mix) + breadthRecord(value.forward_breadth);
  const headline = tally.PASS || tally.NARROW_PASS ? "answerPassed" : "answerNone";
  setHTML("overview-answer", `${stale}${checkpointBanner(value)}<p class="answer-headline">${esc(t(headline))}</p>${trialOutcomes(tally, verdicts)}`
    + `<details class="answer-trials" data-key="trial-register"><summary data-focus="trial-register">${esc(t("answerShowTrials"))}</summary>`
    + `<label class="trial-filter" for="trial-verdict-filter">${esc(t("answerVerdict"))}<select id="trial-verdict-filter" data-focus="trial-filter">`
    + ["", ...verdicts].map(key => `<option value="${key}"${key === selected ? " selected" : ""}>${esc(t(key ? `verdict${key}` : "answerAllVerdicts"))}</option>`).join("")
    + `</select></label>${programmeLine(value.programme)}`
    + table([t("answerTrial"), t("answerHypothesis"), t("answerVerdict")], filtered.map(row => [
      `${code(row.id)} <small class="muted">${esc(row.registered)}</small>`, `<span dir="ltr">${esc(String(row.hypothesis).replace(/\*\*|`/g, ""))}</span>`,
      chip(t(`verdict${row.verdict}`), kinds[row.verdict])]), t("answerNoMatches"))
    + `</details><section class="trial-forward"><h3>${esc(t("answerForward"))}</h3>${journals || `<p class="muted">${esc(t("answerForwardNone"))}</p>`}</section>`);
}

function trialOutcomes(tally, verdicts) {
  const counts = verdicts.map(verdict => Number.isSafeInteger(tally[verdict]) && tally[verdict] > 0 ? tally[verdict] : 0);
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!total) return empty(t("answerNoMatches"));
  let x = 0;
  const parts = verdicts.map((verdict, i) => {
    const width = counts[i];
    const rect = `<rect class="trial-${verdict}" x="${x}" width="${width}" y="0" height="12"/>`;
    x += width;
    return rect;
  }).join("");
  return `<figure class="trial-outcomes"><figcaption>${num(total)} ${esc(t("answerRegistered"))}</figcaption>`
    + `<svg viewBox="0 0 ${total} 12" preserveAspectRatio="none" aria-hidden="true">${parts}</svg>`
    + `<ul class="trial-counts">${verdicts.map((verdict, i) => `<li><span class="trial-swatch trial-${verdict}" aria-hidden="true"></span><strong>${num(counts[i])}</strong> ${esc(t(`verdict${verdict}`))}</li>`).join("")}</ul></figure>`;
}

/** Truthful evidence stage, DISARMED authority, trial budget, and owner backup exception (U001, U002, U004, U006, U031). */
function checkpointBanner(value) {
  const cp = value?.checkpoint;
  const budget = value?.trial_budget;
  if (!cp && !budget) return "";
  const pills = [
    chip(t("evidenceBadgeDisarmed"), "warn"),
    chip(t("evidenceBadgePaper"), "neutral"),
    cp?.backup_policy_exception ? chip(t("backupExceptionBadge"), "warn") : "",
  ].filter(Boolean).join(" ");
  const meta = [];
  if (cp?.date) meta.push(`${esc(t("checkpointDateLabel"))}: <span dir="ltr">${esc(cp.date)}</span>`);
  if (budget) meta.push(`${esc(t("trialBudgetLabel"))}: <span dir="ltr">${digits(budget.active)}/${digits(budget.limit)}</span>`);
  return `<div class="checkpoint-strip" role="note"><p>${pills}</p>${meta.length ? `<p class="field-help">${meta.join(" · ")}</p>` : ""}</div>`;
}

/** The breadth-trend forward paper record on Wallex USDT markets (U005). */
function breadthRecord(breadth) {
  if (!breadth) return "";
  return `<h4 class="forward-title">${esc(t("breadthTitle"))}</h4>` + keyValues([
    [t("forwardDays"), `${num(breadth.days)} · ${esc(t("mixSince"))} <span dir="ltr">${esc(breadth.started)}</span>`],
    [t("mixEquity"), `<span class="${signed(breadth.net_pct)}" dir="ltr">${digits(breadth.equity)} USDT · ${digits(breadth.net_pct)}%</span>`],
    [t("breadthGate"), `${esc(t(breadth.gate_open ? "breadthGateOpen" : "breadthGateClosed"))} · ${esc(t("breadthUniverse"))}: ${num(breadth.universe_size)}`],
    [t("forwardLatest"), stampHtml(breadth.latest)],
  ]);
}

/** The passive mix's forward record on Wallex prices, beside the trend rule's. */
function mixRecord(mix) {
  if (!mix) return "";
  return `<h4 class="forward-title">${esc(t("mixTitle"))}</h4>` + keyValues([
    [t("forwardDays"), `${num(mix.days)} · ${esc(t("mixSince"))} ${esc(mix.started)}`],
    [t("mixEquity"), `<span class="${signed(mix.net_pct)}">${digits(mix.equity)} USDT · ${digits(mix.net_pct)}%</span>`],
    [t("mixInvested"), `${digits(mix.invested_pct ?? "")}%`], [t("forwardLatest"), stampHtml(mix.latest)]]);
}

/** Show the adjusted score without treating it as an individual probability of error. */
function programmeLine(value) {
  if (!value) return "";
  return `<p class="field-help">${esc(t("programmeLine").replace("{best}", value.best).replace("{p}", digits(value.best_probability.toFixed(3)))
    .replace("{count}", value.completed).replace("{q}", digits(value.best_q.toFixed(2))))}</p>`;
}

/** The prospective record beside the historical verdict it follows; amounts only, no profit claim. */
function forwardRecord(forward, historical, kinds) {
  if (!forward) return "";
  return `<h4 class="forward-title">${esc(t("forwardTitle"))}</h4>${forwardComparison(forward)}` + keyValues([
    [t("forwardHistorical"), historical ? chip(t(`verdict${historical.verdict}`), kinds[historical.verdict]) : esc(t("none"))],
    [t("forwardDays"), esc(t("forwardDaysValue").replace("{days}", forward.days).replace("{missing}", forward.missing_days).replace("{withheld}", forward.withheld))],
    [t("forwardTrades"), `${num(forward.trades)} · ${digits(rounded(forward.fees, 2))} USDT ${esc(t("forwardFees"))}`],
    [t("forwardLatest"), stampHtml(forward.latest)],
  ]);
}

function forwardComparison(forward) {
  const rows = [[t("forwardStrategy"), forward.net], [t("forwardCash"), "0"],
    [t("forwardVsHold").replace("{coin}", forward.symbol.replace(/USDT$/, "")), forward.hold_net]];
  return netBars(rows, t("forwardChange"), t("forwardHoldNoCosts"));
}

/** Summarize qualified markets and saved paper evidence without making profit claims. */
function renderOverview() {
  renderAnswer();
  const markets = list(state.markets?.markets), runs = list(state.overviewRuns), latest = runs[0];
  setHTML("overview-summary", stat(t("observedPairs"), state.markets ? num(markets.length) : t("none"), t("observedPairsNote"))
    + stat(t("healthyQuotes"), state.markets ? num(markets.filter(healthyQuote).length) : t("none"), state.markets ? `${t("healthyQuotesNote")} · ${when(state.markets.now)}` : t("healthyQuotesNote"))
    + stat(t("savedRunCount"), state.overviewRuns ? num(runs.length) : t("none"), t("runCountNote"))
    + stat(t("latestNet"), latest?.end ? `<span class="${signed(latest.end.net)}">${money(latest.end.net)}</span> <small>${esc(/(TMN|USDT)$/.exec(latest.inputs?.symbol || "")?.[1] || "")}</small>` : esc(t("none")), latest?.inputs?.to ? `${t("latestNetNote")} · ${when(latest.inputs.to)}` : t("latestNetNote")));
  setHTML("overview-markets", state.markets ? table([t("pair"), t("bid"), t("ask"), t("spreadBps"), t("entry")], markets.slice(0, 5).map(m => [code(m.symbol), amount(m.bid), amount(m.ask), amount(m.spread_bps), eligibility(m.act?.entry)]), t("noMarkets"), [1, 2, 3]) : empty(t("loading")));
  const quote = /(TMN|USDT)$/.exec(latest?.inputs?.symbol || "")?.[1] || "";
  setHTML("overview-research", latest ? `<div class="run-heading"><h3>${code(latest.inputs?.symbol)} <span class="muted">${esc(latest.inputs?.strategy || "")}</span></h3>${chip(t(latest.inputs?.store === "demo" ? "synthetic" : "paperOnly"))}</div>${keyValues([[t("net"), `${money(latest.end?.net)} ${code(quote)}`], [t("equity"), `${money(latest.end?.equity)} ${code(quote)}`], [t("window"), `${stampHtml(latest.inputs?.from)} → ${stampHtml(latest.inputs?.to)}`]])}<a class="button button-small" href="#research/runs/${esc(latest.run_id)}">${esc(t("inspectRun"))}</a>` : empty(t(state.overviewRuns ? "noRuns" : "loading"), t("noRunsHelp")));
  setHTML("overview-activity", runs.length ? table([t("pair"), t("time"), t("net")], runs.slice(0, 4).map(run => [code(run.inputs?.symbol), stampHtml(run.inputs?.to), `${money(run.end?.net)} ${code(/(TMN|USDT)$/.exec(run.inputs?.symbol || "")?.[1])}`]), "", [2]) : empty(t(state.overviewRuns ? "recentEvidenceEmpty" : "loading")));
}

/** Show connection and readiness failures explicitly, including unknown feed state. */
function renderFeed() {
  const health = state.health;
  const key = state.apiError ? "refreshFailed" : !health ? "feedUnknown" : health.fatal ? "feedStopped" : health.connected ? "feedConnected" : "feedDisconnected";
  const readiness = health?.readiness;
  const ready = list(readiness?.markets).filter(row => row.state === "READY").length;
  setHTML("feed-status", `<span class="dot${state.apiError || health?.fatal || !health?.connected || readiness?.ready !== true ? " dot-warn" : ""}" aria-hidden="true"></span><span>${esc(t(key))}${readiness ? ` · ${esc(t("publicReadiness"))}: ${label(readiness.status)} · ${digits(ready)}/${digits(list(readiness.markets).length)}` : ""}</span>`);
  $("connection-error").hidden = !state.apiError;
  const detail = $("connection-error-detail");
  if (detail) detail.textContent = state.apiError ? ` ${t("failedSources")}: ${(state.apiErrorSources ?? []).join(", ")}` +
    (state.lastGoodRefresh ? ` · ${t("lastCompleteRefresh")} ${when(state.lastGoodRefresh.toISOString())}` : "") : "";
}
/** Render the wall clock in Tehran time using the active locale. */
function updateClock() {
  const now = new Date();
  $("clock").textContent = new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", { timeZone: "Asia/Tehran", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(now) + " · " + t("tehranCity");
  $("clock").setAttribute("datetime", now.toISOString());
}
