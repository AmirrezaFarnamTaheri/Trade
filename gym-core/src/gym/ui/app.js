let pollTimer, refreshTask, refreshAgain = false;
/** Await named reads together; throw one error naming every source that failed, so the banner can say which. */
async function settled(named) {
  const results = await Promise.allSettled(named.map(([, task]) => task));
  const failed = named.filter((_, i) => results[i].status === "rejected").map(([source]) => source);
  if (failed.length) throw Object.assign(new Error(t("requestError")), { sources: failed });
}
/** Refresh one visible workspace view from read-only or explicitly approved APIs. */
async function collectView(name, healthTask) {
  if (name === "operate") window.gymNativeReview?.mount(api, DEMO);
  if (name === "backups") {
    try {
      const value = await api("/api/backup-status");
      setHTML("backup-operation-status", `<p>${code(value.state)}</p><p>${esc(t("backupReceiptScope"))}</p>` + (value.state === 'NO_RECEIPTS'
        ? `<p>${esc(t("noBackupReceipts"))}</p>` : Object.entries(value.latest ?? {}).filter(([, row]) => row).map(([kind, row]) =>
          `<article><h3>${esc(t(kind === 'BACKUP' ? 'backupWorkflow' : 'restoreWorkflow'))}</h3><p>${stampHtml(row.recorded_at)}</p><pre class="output" dir="ltr">${esc(JSON.stringify(row, null, 2))}</pre></article>`).join('')));
    } catch (error) { setHTML("backup-operation-status", `<p>${esc(t("requestError"))}</p>`); throw error; }
  }
  if (name === "overview") {
    try {
      await settled([["markets", api("/api/markets").then(data => { state.markets = data; renderMarkets(); })],
        ["research", research().then(() => { state.runsLoaded = true; })], ["operate", operate()]]);
    } finally { renderOverview(); }
  }
  if (name === "markets") { state.markets = await api("/api/markets"); renderMarkets(); }
  if (name === "research") {
    window.gymResearch?.mount(api, esc);
    window.gymMargin?.mount({api, esc, keyValues, table, amount, when, stamp: stampHtml, demo: DEMO}); window.gymPortfolio?.mount({api, esc, table, keyValues, amount, when, stamp: stampHtml, curveFigure, strategyFields});
    await settled([["research", research()], ["research jobs", researchJobs()]]);
  }
  if (name === "account") {
    await settled([["account journal", accountJournal()], ["external journal", externalJournal()], ["offline reviews", offlineReviews()]]);
  }
  if (name === "operate" || name === "safety") await operate();
  if (name === "rules") await rules();
  if (name === "health") {
    await settled([["health", healthTask.then(renderHealth)], ["venue facts", venueFacts()], ["chaos report", chaos()]]);
  }
}

/** Serialize polling, pause while hidden, and surface network failures. */
async function refresh() {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  if (refreshTask) { refreshAgain = true; return refreshTask; }
  const name = state.view;
  updateClock();
  refreshTask = (async () => {
    const healthTask = api("/api/health").then(data => { state.health = data; checkAlerts(data); return data; });
    const results = await Promise.allSettled([healthTask, collectView(name, healthTask)]);
    if (state.view === name) {
      const [health, view] = results;
      state.apiErrorSources = [...new Set([...(health.status === "rejected" ? ["health"] : []),
        ...(view.status === "rejected" ? view.reason?.sources ?? [name] : [])])];
      state.apiError = state.apiErrorSources.length > 0;
      state.refreshFailures = state.apiError ? (state.refreshFailures || 0) + 1 : 0;
      if (!state.apiError) state.lastGoodRefresh = new Date();
    }
    renderFeed();
  })();
  try { await refreshTask; }
  finally {
    refreshTask = null;
    const again = refreshAgain; refreshAgain = false;
    // Back off while the service keeps failing (2 s, 4 s, 8 s ... at most 30 s); recover at once on success.
    const delay = Math.min(2000 * 2 ** (state.refreshFailures || 0), 30000);
    if (!document.hidden) pollTimer = setTimeout(refresh, again ? 0 : delay);
  }
}
const viewKeys = { overview: "navOverview", markets: "navMarkets", research: "navResearch", account: "navAccount", operate: "navOperate", rules: "navRules", health: "navHealth", safety: "navSafety", backups: "navBackups" };
/** Navigate to a known workspace view while preserving keyboard focus. */
async function showView(name, focus = false) {
  if (!Object.hasOwn(viewKeys, name)) name = "overview";
  state.view = name;
  document.querySelectorAll("[data-view]").forEach(link => {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  Object.keys(viewKeys).forEach(view => { $("v-" + view).hidden = view !== name; });
  $("current-view").textContent = t(viewKeys[name]);
  if (focus) $("main").focus({ preventScroll: false });
  return refresh();
}

// Deep links: #research/<tab>[/<run id>] opens a research tab and, for runs, a saved run.
/** Decode a supported deep link without granting any execution capability. */
function route(hash) {
  const [name, tab, id] = hash.slice(1).split("/");
  if (name === "research" && researchTabs.includes(tab)) {
    showResearchTab(tab, false, false);
    if (tab === "runs" && /^[0-9a-f]{16}$/.test(id || "")) { state.selectedRun = state.pinnedRun = id; state.record = null; }
  }
  return name;
}
/** Keep the research-tab deep link synchronized with current selection. */
function linkResearch() {
  if (state.view !== "research") return;
  const id = researchTab === "runs" && state.selectedRun ? "/" + state.selectedRun : "";
  history.replaceState(null, "", `${location.pathname}${location.search}#research/${researchTab}${id}`);
}
window.addEventListener?.("hashchange", () => {
  const name = route(location.hash);
  if (!name || Object.hasOwn(viewKeys, name)) showView(name, true);
});
document.addEventListener("visibilitychange", () => { clearTimeout(pollTimer); if (!document.hidden) refresh(); });
