$("ticket-example").onclick = () => {
  invalidateTicket();
  $("offline-ticket").value = JSON.stringify(syntheticTicket(), null, 2);
  renderTicketFields();
  $("offline-ticket").removeAttribute("aria-invalid");
  setHTML("ticket-output", `<p class="field-help">${esc(t("syntheticExample"))}</p>`);
};
$("preview-ticket").onclick = previewTicket;
/** Save an explicitly selected offline review; failures never imply funded authority. */
async function writeOfflineReview(button, action, value) {
  button.disabled = true;
  const status = action === "record" ? $("ticket-output") : $("offline-review-status");
  try {
    const result = await api("/api/offline-ticket-reviews", { method: "POST", body: JSON.stringify({ action, value }) });
    if (action === "record" && currentPreview === value) setHTML("ticket-output", `<p role="status">${esc(t("journalSaved"))} · ${code(result.preview_sha256)}</p>`);
    else if (action === "review") status.textContent = `${t("journalSaved")} · ${result.state}`;
    await offlineReviews();
  } catch { if (action !== "record" || currentPreview === value) status.textContent = t("reviewWriteError"); }
  finally { if (button.isConnected) button.disabled = false; }
}
$("ticket-output").addEventListener("click", event => {
  const button = event.target.closest?.("#save-preview");
  if (button && currentPreview) writeOfflineReview(button, "record", currentPreview);
});
$("offline-review-events").addEventListener("click", event => {
  const button = event.target.closest?.("[data-review-key]");
  if (button) writeOfflineReview(button, "review", { preview_sha256: button.dataset.reviewKey, decision: button.dataset.decision });
});
$("offline-ticket").addEventListener("input", invalidateTicket);
$("ticket-fields").addEventListener("input", editTicketField);
$("ticket-fields").addEventListener("change", editTicketField);
$("ticket-editor-mode").addEventListener("click", event => {
  const button = event.target.closest?.("[data-editor]");
  if (!button) return;
  const useJson = button.dataset.editor === "json";
  if (!useJson) renderTicketFields();
  $("ticket-fields").hidden = useJson; $("ticket-json-panel").hidden = !useJson;
  document.querySelectorAll("[data-editor]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
});
$("rule-rows").addEventListener("click", event => {
  const button = event.target.closest?.("[data-disable]") || event.target, id = button.dataset.disable;
  if (!id || !confirm(`${t("disableConfirm")}\n${id}`)) return;
  changeRule(button, async () => { await api("/api/rules/" + encodeURIComponent(id) + "/disable", { method: "POST" }); $("rule-action-result").textContent = t("ruleSaved"); });
});
$("load-preset").onclick = () => {
  if (!confirm(t("presetConfirm"))) return;
  changeRule($("load-preset"), async () => { await api("/api/presets/usdt-irt-october-2026", { method: "POST" }); $("rule-action-result").textContent = t("presetSaved"); });
};
$("rule-import-submit").onclick = async () => {
  const input = $("rule-import"), button = $("rule-import-submit");
  if (state.savingRules) return;
  button.disabled = true; button.setAttribute("aria-busy", "true"); input.removeAttribute("aria-invalid");
  try {
    if (!Array.isArray(JSON.parse(input.value))) throw new Error("expected list");
    const result = await api("/api/rules/import", { method: "POST", body: input.value });
    $("rule-import-result").textContent = `${digits(result.imported)} ${t("imported")} · ${digits(list(result.quarantined).length)} ${t("quarantined")}`;
    await rules();
  } catch (_) { input.setAttribute("aria-invalid", "true"); $("rule-import-result").textContent = t("importError"); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); }
};
