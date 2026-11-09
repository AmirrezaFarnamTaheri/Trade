const $ = id => document.getElementById(id);
/** Read an optional persisted preference only when its value is allowed. */
function saved(key, fallback, allowed) {
  try { const value = localStorage.getItem(key); return allowed.includes(value) ? value : fallback; }
  catch (_) { return fallback; }
}
/** Labelled, bilingual confirmation with the consequence in view; focus returns to the trigger. Falls back to confirm(). */
function confirmAction(message, actionLabel, trigger) {
  if (typeof document.createElement !== "function" || typeof HTMLDialogElement === "undefined") return Promise.resolve(confirm(message));
  return new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirm-dialog-text");
    dialog.innerHTML = `<p id="confirm-dialog-text"></p><div class="toolbar"><button type="button" class="button" value="cancel"></button><button type="button" class="button button-primary" value="ok"></button></div>`;
    dialog.querySelector("p").textContent = message;
    const [cancel, ok] = dialog.querySelectorAll("button");
    cancel.textContent = t("cancelAction"); ok.textContent = actionLabel;
    const finish = answer => { dialog.close(); dialog.remove(); trigger?.focus?.(); resolve(answer); };
    cancel.onclick = () => finish(false); ok.onclick = () => finish(true);
    dialog.addEventListener("cancel", event => { event.preventDefault(); finish(false); });
    document.body.append(dialog);
    dialog.showModal();
    cancel.focus();  // the safe choice has focus; Enter does not confirm by accident
  });
}
/** Persist a non-secret workspace preference when browser storage is available. */
function remember(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* Storage is optional. */ } }
let lang = saved("lang", "en", ["en", "fa"]);
/** First visit follows the operating system; an explicit toggle is remembered and wins afterwards. */
function systemTheme() {
  try { return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"; }
  catch (_) { return "light"; }
}
let theme = saved("theme", systemTheme(), ["light", "dark"]);
const state = { view: "overview", markets: null, quote: "", filter: "", expanded: "", runs: [], runCount: 50, runFilter: "", pickedRuns: new Set(), overlays: new Map(),
  selectedRun: "", record: null, health: null, rules: null, apiError: false, savingRules: false,
  researchSetup: null, researchState: null, researchBusy: false, comparison: null, comparing: false, candidateParams: {} };
let comparisonRevision = 0;
const t = key => T[lang][key] ?? key;
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const digits = value => lang === "fa" ? String(value).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]) : String(value);
// Keep API money as decimal strings; floating point is used only for chart geometry.
/** Display exact decimal-string money with locale digits and no floating-point conversion. */
function num(value) {
  if (value == null || value === "") return t("none");
  const raw = String(value), match = raw.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return esc(raw);
  return digits(match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (match[3] ? "." + match[3] : ""));
}
/** Format a timestamp in the selected UI language and requested time zone. */
function when(value, dateOnly = false, timeZone = "Asia/Tehran") {
  if (!value) return t("none");
  const stamp = new Date(value);
  if (!Number.isFinite(stamp.getTime())) return t("unknown");
  return new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", {
    timeZone, year: "numeric", month: "short", day: "numeric",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit" }),
  }).format(stamp);
}
// Round a decimal string half-up for display only; the exact value stays in the tooltip.
/** Round a decimal string for display only; never alter stored precision. */
function rounded(value, places = 2) {
  const match = String(value ?? "").match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match || (match[3] || "").length <= places) return value;
  const [, sign, whole, fraction] = match;
  let scaled = whole + fraction.slice(0, places);
  if (fraction[places] >= "5") scaled = (BigInt(scaled) + 1n).toString().padStart(scaled.length, "0");
  const text = places ? `${scaled.slice(0, -places) || "0"}.${scaled.slice(-places)}` : scaled;
  return /^[0.]*$/.test(text) ? text : sign + text;
}
// U+2066/U+2069 isolate a signed figure left-to-right in Persian text, and survive HTML escaping.
const ratio = (value, places = 2) => value == null || !Number.isFinite(Number(value)) ? t("none") : `\u2066${digits(Number(value).toFixed(places))}\u2069`;
const percent = (value, places = 1) => value == null || !Number.isFinite(Number(value)) ? t("none") : `\u2066${digits((Number(value) * 100).toFixed(places))} %\u2069`;
const signed = value => String(value ?? "").startsWith("-") ? "neg" : Number(value) > 0 ? "pos" : "";
const list = value => Array.isArray(value) ? value : [];
const code = value => `<bdi dir="ltr">${esc(value ?? t("none"))}</bdi>`;
const amount = value => `<bdi dir="ltr">${num(value)}</bdi>`;
const money = (value, places = 2) => value == null || value === "" ? esc(t("none")) : `<bdi dir="ltr" title="${esc(num(value))}">${num(rounded(value, places))}</bdi>`;
const label = value => esc(t(String(value ?? "unknown")));
const chip = (text, kind = "warn") => `<span class="chip chip-${kind}">${esc(text)}</span>`;
const empty = (title, help = "") => `<div class="empty-state"><p class="empty-title">${esc(title)}</p>${help ? `<p class="field-help">${esc(help)}</p>` : ""}</div>`;
const json = value => `<pre class="output mono" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
const disclosure = (title, value, key) => `<details class="disclosure" data-key="${esc(key)}"><summary>${esc(title)}</summary>${json(value)}</details>`;
const stat = (name, value, note = "") => `<div class="stat"><span class="stat-label">${esc(name)}</span><strong class="stat-value">${value}</strong>${note ? `<span class="stat-note">${esc(note)}</span>` : ""}</div>`;
const keyValues = rows => `<dl class="key-values">${rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
// `numeric` lists column indexes that hold numbers: right-aligned, tabular figures.
/** Render accessible responsive rows, preserving numeric column alignment. */
function table(headings, rows, fallback, numeric = []) {
  if (!rows.length) return empty(fallback || t("nothing"));
  const cls = i => numeric.includes(i) ? ' class="num"' : "";
  return `<div class="table-wrap" tabindex="0"><table class="data"><thead><tr>${headings.map((h, i) => `<th scope="col"${cls(i)}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map((cell, i) => `<td${cls(i)} data-label="${esc(headings[i] ?? "")}">${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const rendered = new Map();
/** Refresh a view without closing disclosure panels or stealing keyboard focus. */
function setHTML(id, html) {
  const element = $(id);
  if (rendered.get(id) === html) return;
  const open = new Set([...element.querySelectorAll("details[data-key]")].filter(detail => detail.open).map(detail => detail.dataset.key));
  const focus = document.activeElement?.dataset?.focus;
  const focusedInside = focus && [...element.querySelectorAll("[data-focus]")].includes(document.activeElement);
  element.innerHTML = html;
  rendered.set(id, html);
  for (const detail of element.querySelectorAll("details[data-key]")) detail.open = open.has(detail.dataset.key);
  if (focusedInside) [...element.querySelectorAll("[data-focus]")].find(node => node.dataset.focus === focus)?.focus({ preventScroll: true });
}

/** Make a bounded same-origin request with token headers and safe error output. */
async function api(path, options = {}, timeoutMs = 10000, asText = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...options, cache: "no-store", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Gym-Token": TOKEN, ...options.headers } });
    if (!response.ok) {
      // Kept off the page by default: some server errors quote submitted material. Callers with non-secret forms opt in.
      const error = new Error(t("requestError"));
      if (response.status < 500) error.detail = await response.json().then(body => typeof body?.error === "string" ? body.error.slice(0, 240) : "", () => "");
      throw error;
    }
    return asText ? await response.text() : await response.json();
  } catch (error) {
    throw Object.assign(new Error(t("requestError")), { detail: error.detail || "" });
  } finally { clearTimeout(timeout); }
}
