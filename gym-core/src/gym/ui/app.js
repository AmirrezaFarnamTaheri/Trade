let pollTimer, refreshTask, refreshAgain = false;
async function collectView(name, healthTask) {
  if (name === "operate") window.gymNativeReview?.mount(api, DEMO);
  if (name === "backups") {
    try {
      const value = await api("/api/backup-status");
      setHTML("backup-operation-status", `<p>${code(value.state)}</p><p>${esc(t("backupReceiptScope"))}</p>` + (value.state === 'NO_RECEIPTS'
        ? `<p>${esc(t("noBackupReceipts"))}</p>` : Object.entries(value.latest ?? {}).filter(([, row]) => row).map(([kind, row]) =>
          `<article><h3>${esc(t(kind === 'BACKUP' ? 'backupWorkflow' : 'restoreWorkflow'))}</h3><p>${esc(when(row.recorded_at))}</p><pre class="output" dir="ltr">${esc(JSON.stringify(row, null, 2))}</pre></article>`).join('')));
    } catch (error) { setHTML("backup-operation-status", `<p>${esc(t("requestError"))}</p>`); throw error; }
  }
  if (name === "models") await window.gymModels?.mount(api, esc);
  if (name === "overview") {
    const results = await Promise.allSettled([
      api("/api/markets").then(data => { state.markets = data; renderMarkets(); }),
      research().then(() => { state.runsLoaded = true; }), operate(),
    ]);
    renderOverview();
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "markets") { state.markets = await api("/api/markets"); renderMarkets(); }
  if (name === "research") {
    window.gymResearch?.mount(api, esc);
    window.gymMargin?.mount({api, esc, keyValues, table, amount, when, demo: DEMO}); window.gymPortfolio?.mount({api, esc, table, keyValues, amount, when, curveFigure, strategyFields});
    const results = await Promise.allSettled([research(), researchJobs()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "account") {
    const results = await Promise.allSettled([accountJournal(), externalJournal(), offlineReviews()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "operate" || name === "safety") await operate();
  if (name === "rules") await rules();
  if (name === "health") {
    const results = await Promise.allSettled([healthTask.then(renderHealth), venueFacts(), chaos()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
}

async function refresh() {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  if (refreshTask) { refreshAgain = true; return refreshTask; }
  const name = state.view;
  updateClock();
  refreshTask = (async () => {
    const healthTask = api("/api/health").then(data => { state.health = data; checkAlerts(data); return data; });
    const results = await Promise.allSettled([healthTask, collectView(name, healthTask)]);
    if (state.view === name) state.apiError = results.some(result => result.status === "rejected");
    renderFeed();
  })();
  try { await refreshTask; }
  finally {
    refreshTask = null;
    const again = refreshAgain; refreshAgain = false;
    if (!document.hidden) pollTimer = setTimeout(refresh, again ? 0 : 2000);
  }
}
const viewKeys = { overview: "navOverview", markets: "navMarkets", research: "navResearch", account: "navAccount", operate: "navOperate", rules: "navRules", health: "navHealth", safety: "navSafety", backups: "navBackups", models: "navModels" };
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
function route(hash) {
  const [name, tab, id] = hash.slice(1).split("/");
  if (name === "research" && researchTabs.includes(tab)) {
    showResearchTab(tab, false, false);
    if (tab === "runs" && /^[0-9a-f]{16}$/.test(id || "")) { state.selectedRun = state.pinnedRun = id; state.record = null; }
  }
  return name;
}
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
