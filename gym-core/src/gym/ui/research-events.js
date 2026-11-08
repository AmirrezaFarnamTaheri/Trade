const researchTabs = ["runs", "compare", "schedules", "margin", "workbench"];
let researchTab = saved("researchTab", "runs", researchTabs);
/** Select a research subview and keep URL history, focus, and ARIA state aligned. */
function showResearchTab(name, focus = false, link = true) {
  if (name !== researchTab) window.scrollTo?.({ top: 0 });
  researchTab = name; remember("researchTab", name);
  document.querySelectorAll("#research-tabs [role=tab]").forEach(tab => {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(on)); tab.tabIndex = on ? 0 : -1;
    if (on && focus) tab.focus();
  });
  for (const tab of researchTabs) $("panel-" + tab).hidden = tab !== name;
  if (link) linkResearch();
}
$("research-tabs").addEventListener("click", event => {
  const tab = event.target.closest?.("[data-tab]") || event.target;
  if (tab.dataset.tab) showResearchTab(tab.dataset.tab);
});
$("research-tabs").addEventListener("keydown", event => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key] * (document.documentElement.dir === "rtl" ? -1 : 1);
  const index = event.key === "Home" ? 0 : event.key === "End" ? researchTabs.length - 1
    : step ? (researchTabs.indexOf(researchTab) + step + researchTabs.length) % researchTabs.length : -1;
  if (index < 0) return;
  event.preventDefault(); showResearchTab(researchTabs[index], true);
});
showResearchTab(researchTab);
/** Choose a persisted research run and refresh its evidence without changing records. */
function selectSavedRun(event) {
  const button = event.target.closest?.("[data-run]") || event.target;
  if (!button.dataset.run) return;
  state.selectedRun = button.dataset.run; state.record = null; state.savedComparison = false;
  showResearchTab("runs"); renderRunList(); refresh();
}
$("run-list").addEventListener("click", selectSavedRun);
$("run-list").addEventListener("change", event => {
  const id = event.target.dataset?.pick;
  if (!id) return;
  if (event.target.checked && state.pickedRuns.size < 4) state.pickedRuns.add(id); else { state.pickedRuns.delete(id); event.target.checked = false; }
  renderRunList();
});
$("compare-picked").addEventListener("click", async () => {
  setHTML("run-detail", empty(t("loading")));
  try {
    const records = await Promise.all([...state.pickedRuns].map(id => api("/api/runs/" + encodeURIComponent(id))));
    state.selectedRun = ""; state.record = null; renderRunList();
    renderSavedComparison(records);
  } catch (_) { setHTML("run-detail", empty(t("runReadError"))); }
});
$("run-filter").addEventListener("change", () => { state.runFilter = $("run-filter").value.trim().toUpperCase(); state.runCount = 50; refresh(); });
$("run-more").addEventListener("click", () => { state.runCount = Math.min(200, state.runCount + 50); refresh(); });
$("run-detail").addEventListener("click", async event => {
  const csvButton = event.target.closest?.("[data-csv]");
  if (csvButton && state.record) { exportCsv(csvButton.dataset.csv, state.record); return; }
  const goto = event.target.closest?.("[data-goto-tab]");
  if (goto) { showResearchTab(goto.dataset.gotoTab, true); return; }
  const button = event.target.closest?.("[data-export-run]") || event.target;
  if (!button.dataset.exportRun) return;
  button.disabled = true;
  try {
    const html = button.dataset.format === "html";
    const card = await api("/api/runs/" + encodeURIComponent(button.dataset.exportRun) + (html ? "/summary.html" : "/summary"), {}, 10000, html);
    const url = URL.createObjectURL(new Blob([html ? card : JSON.stringify(card, null, 2)], { type: html ? "text/html" : "application/json" }));
    try {
      const link = document.createElement("a");
      link.href = url; link.download = `paper-${button.dataset.exportRun}.${html ? "html" : "json"}`; link.click();
    } finally { URL.revokeObjectURL(url); }
  } catch (_) { state.apiError = true; renderFeed(); }
  finally { button.disabled = false; }
});
$("compare-result").addEventListener("click", selectSavedRun);
$("compare-form").addEventListener("submit", submitComparison);
$("validate-submit").onclick = event => submitComparison(event, true);
$("research-tick").onclick = () => controlResearch("tick");
$("research-jobs").addEventListener("click", event => {
  const button = event.target.closest?.("[data-research-action]") || event.target;
  if (button.dataset.researchAction) controlResearch(button.dataset.researchAction, button.dataset.job);
  else selectSavedRun(event);
});
$("compare-form").addEventListener("input", event => {
  const { slot, parameter } = event.target.dataset;
  if (parameter) { state.candidateParams[slot] ||= {}; state.candidateParams[slot][parameter] = event.target.value; }
  invalidateComparison();
});
for (const slot of ["first", "second"]) $("candidate-" + slot).addEventListener("change", () => {
  state.candidateParams[slot] = {}; invalidateComparison(); renderCandidate(slot);
});
$("compare-symbol").addEventListener("change", () => { invalidateComparison(); setupResearch($("compare-symbol").value); });
