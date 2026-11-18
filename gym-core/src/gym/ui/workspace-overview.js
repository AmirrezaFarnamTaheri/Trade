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
  if (!value || value.state !== "READY") return setHTML("overview-answer", empty(t(value ? "answerNoLog" : "loading")));
  const tally = value.tally, forward = value.forward, kinds = { FAIL: "bad", NARROW_PASS: "warn", PASS: "ok", OPEN: "warn" };
  const headline = tally.PASS ? "answerPassed" : tally.NARROW_PASS ? "answerNarrow" : "answerNone";
  const plain = text => esc(String(text).replace(/\*\*|`/g, ""));
  const change = forward?.net == null ? t("unavailable") : digits(rounded(forward.net, 2));
  setHTML("overview-answer", `<p class="answer-headline">${esc(t(headline))}</p><div class="stats answer-stats">`
    + stat(t("answerRegistered"), num(tally.registered), t("answerRegisteredNote"))
    + stat(t("answerFailed"), num(tally.FAIL), t("answerFailedNote"))
    + stat(t("answerNarrowCount"), num(tally.NARROW_PASS + tally.PASS), t("answerNarrowNote"))
    + stat(t("answerForward"), forward ? `${num(forward.days)} <small>${esc(t("answerDays"))}</small>` : esc(t("none")),
      forward ? `${forward.symbol} · ${t(forward.in_market ? "answerInMarket" : "answerInCash")} · ${change} USDT` : t("answerForwardNone"))
    + `</div>${programmeLine(value.programme)}${forwardRecord(forward, value.trials.find(row => row.id === "btc-daily-trend"), kinds)}<details class="answer-trials"><summary>${esc(t("answerShowTrials"))}</summary>`
    + table([t("answerTrial"), t("answerHypothesis"), t("answerVerdict")], value.trials.map(row => [
      `${code(row.id)} <small class="muted">${esc(row.registered)}</small>`, `<span dir="ltr">${plain(row.hypothesis)}</span>`,
      chip(t(`verdict${row.verdict}`), kinds[row.verdict])]), t("nothing")) + "</details>");
}

/** The best result after correcting for every trial run: a q-value near 1 means it is as likely luck as not. */
function programmeLine(value) {
  if (!value) return "";
  return `<p class="field-help">${esc(t("programmeLine").replace("{best}", value.best).replace("{p}", digits(value.best_probability.toFixed(3)))
    .replace("{count}", value.completed).replace("{q}", digits(value.best_q.toFixed(2))))}</p>`;
}

/** The prospective record beside the historical verdict it follows; amounts only, no profit claim. */
function forwardRecord(forward, historical, kinds) {
  if (!forward) return "";
  const usdt = value => value == null ? esc(t("unavailable")) : `<span class="${signed(value)}">${digits(rounded(value, 2))} USDT</span>`;
  return `<h3 class="forward-title">${esc(t("forwardTitle"))}</h3>` + keyValues([
    [t("forwardHistorical"), historical ? chip(t(`verdict${historical.verdict}`), kinds[historical.verdict]) : esc(t("none"))],
    [t("forwardDays"), esc(t("forwardDaysValue").replace("{days}", forward.days).replace("{missing}", forward.missing_days).replace("{withheld}", forward.withheld))],
    [t("forwardTrades"), `${num(forward.trades)} · ${digits(rounded(forward.fees, 2))} USDT ${esc(t("forwardFees"))}`],
    [t("forwardVsUsdt"), usdt(forward.net)],
    [t("forwardVsHold").replace("{coin}", forward.symbol.replace(/USDT$/, "")), usdt(forward.hold_net)],
    [t("forwardLatest"), stampHtml(forward.latest)],
  ]);
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
