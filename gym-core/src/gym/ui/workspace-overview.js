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
  if (state.view === "research") { window.gymResearch?.mount(api, esc); window.gymMargin?.mount({api, esc, keyValues, table, amount, when, stamp: stampHtml, demo: DEMO}); window.gymPortfolio?.mount({api, esc, table, keyValues, amount, when, stamp: stampHtml, curveFigure, strategyFields}); }
}

/** Summarize qualified markets and saved paper evidence without making profit claims. */
function renderOverview() {
  const markets = list(state.markets?.markets), latest = state.runs[0];
  setHTML("overview-summary", stat(t("observedPairs"), state.markets ? num(markets.length) : t("none"), t("observedPairsNote"))
    + stat(t("healthyQuotes"), state.markets ? num(markets.filter(healthyQuote).length) : t("none"), t("healthyQuotesNote"))
    + stat(t("savedRunCount"), state.runsLoaded ? num(state.runs.length) : t("none"), t("runCountNote"))
    + stat(t("latestNet"), latest?.end ? `<span class="${signed(latest.end.net)}">${money(latest.end.net)}</span> <small>${esc(/(TMN|USDT)$/.exec(latest.inputs?.symbol || "")?.[1] || "")}</small>` : esc(t("none")), t("latestNetNote")));
  setHTML("overview-markets", state.markets ? table([t("pair"), t("bid"), t("ask"), t("spreadBps"), t("entry")], markets.slice(0, 5).map(m => [code(m.symbol), amount(m.bid), amount(m.ask), amount(m.spread_bps), eligibility(m.act?.entry)]), t("noMarkets"), [1, 2, 3]) : empty(t("loading")));
  const record = state.record, result = record?.result;
  setHTML("overview-research", result ? `<div class="run-heading"><h3>${code(result.symbol)} <span class="muted">${esc(result.strategy || "")}</span></h3>${chip(t(record.inputs?.store === "demo" ? "synthetic" : "paperOnly"))}</div>${curveFigure(result)}${keyValues([[t("net"), `${money(result.end?.net)} ${code(result.quote)}`], [t("totalReturn"), pct(record.evidence?.performance?.total_return_pct)], [t("fills"), num(result.fills)]])}<p class="field-help">${esc(record.evidence?.primary_limitation || t("noCapital"))}</p>` : empty(t(state.runsLoaded ? "noRuns" : "loading"), t("noRunsHelp")));
  setHTML("overview-activity", state.runs.length ? table([t("pair"), t("time"), t("net")], state.runs.slice(0, 4).map(run => [code(run.inputs?.symbol), stampHtml(run.inputs?.to), `${money(run.end?.net)} ${code(/(TMN|USDT)$/.exec(run.inputs?.symbol || "")?.[1])}`]), "", [2]) : empty(t(state.runsLoaded ? "recentEvidenceEmpty" : "loading")));
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
