const { token: TOKEN, demo: DEMO } = JSON.parse(document.getElementById("gym-config").textContent);
const T = {
  en: { operate:"Operate (offline only)", operateWarning:"DISARMED. No real order submission, certified venue stops, or Autopilot. Estimates are not live account authority.", protectionHeading:"Protection and authority status", offlineTicketTitle:"Dry-run order ticket", offlineTicketHelp:"Paste a JSON market snapshot and bounded order request. This only previews fees and limits; it never submits a venue order.", previewOffline:"Preview offline", offlineTicketError:"Invalid or unsafe offline ticket", offlineTicketResult:"Offline preview only; order_submitted=false", venueFactsTitle:"Venue capability evidence (read-only)", venueFactsEmpty:"No venue evidence yet; trading remains disabled", venueFactsInfo:"Source unverified. No order method or automated trading is certified.", venueFactsError:"Venue validation unavailable", venueFactsUnverified:"unverified origin", externalHistory:"External order observations (unverified)", externalEmpty:"No externally observed orders", externalReadError:"External Journal unavailable", accountRead:"Venue account (read-only)", accountNotConfigured:"Not configured · no account or trading credentials loaded", accountError:"Observation unavailable", accountObserved:"Observed (unverified; not managed)", accountBalance:"Balances (venue value / locked; not spendable)", accountOrders:"External/manual orders (not settled)", accountExposure:"External exposure (not managed)", title:"TradingGYM · Observatory", markets:"Markets", rules:"Settings → Venue rules", health:"Health", journal:"Research / Journal", chooseRun:"Paper run", lastDecisions:"Last 100 decisions (expand for marks and order)", evidenceTitle:"Economic evidence (no capital authority)",
        pair:"Pair", bid:"Bid", ask:"Ask", spread:"Spread (bps)", last:"Last trade", quality:"Quality", when:"When can I act?",
        mknote:"Prices are the venue's own quote units (IRT legs in toman, unit epoch 1). Observatory mode: no orders are ever sent.",
        entry:"Buy (entry)", exit:"Sell (exit)", open:"open", blocked:"blocked", until:"until", opens:"opens", closes:"closes", noChange:"no change in 7 days",
        by:"by", source:"source", confirmed:"confirmed", quotaLeft:"quota left", age:"age",
        rulesTitle:"Venue rules", preset:"Load preset: USDT/IRT night closure, October 2026", export:"Export JSON",
        rule:"Rule", cls:"Class / status / source", state:"State", blocksNow:"What does this block right now?", window:"Effective",
        disable:"Disable", importTitle:"Import rules", importHelp:"Paste a JSON list of rules. Malformed rules are quarantined, never applied.",
        import:"Import", nothing:"nothing", version:"rule set version", stale:"stale", none:"—" },
  fa: { operate:"عملیات (فقط آفلاین)", operateWarning:"غیرفعال است. هیچ سفارش واقعی، دستور توقف تأییدشده یا معاملهٔ خودکار فعال نیست. ارقام برآوردی مجوز معامله نیستند.", protectionHeading:"وضعیت حفاظت و مجوز", offlineTicketTitle:"پیش‌نمایش سفارش آزمایشی", offlineTicketHelp:"تصویر بازار و درخواست محدود را در قالب JSON وارد کنید. این بخش فقط هزینه و سقف را محاسبه می‌کند و هیچ سفارشی ارسال نمی‌کند.", previewOffline:"پیش‌نمایش آفلاین", offlineTicketError:"درخواست آزمایشی نامعتبر یا ناامن", offlineTicketResult:"فقط پیش‌نمایش آفلاین؛ بدون ثبت سفارش", venueFactsTitle:"شواهد قابلیت‌های صرافی (فقط خواندنی)", venueFactsEmpty:"هنوز شواهد صرافی ثبت نشده است؛ معاملات غیرفعال است", venueFactsInfo:"منبع تأییدنشده است. هیچ روش سفارش یا معاملهٔ خودکاری مجاز نشده است.", venueFactsError:"اعتبارسنجی صرافی در دسترس نیست", venueFactsUnverified:"منبع تأییدنشده", externalHistory:"مشاهدات سفارش‌های خارجی (تأییدنشده)", externalEmpty:"هیچ سفارش خارجی مشاهده نشده", externalReadError:"دفتر مشاهدات خارجی در دسترس نیست", accountRead:"حساب صرافی (فقط خواندنی)", accountNotConfigured:"پیکربندی نشده · هیچ کلید یا مجوز معامله بارگذاری نشده", accountError:"مشاهده حساب در دسترس نیست", accountObserved:"مشاهده‌شده (تأییدنشده؛ مدیریت‌نشده)", accountBalance:"موجودی (مقدار/بلوکه؛ غیرقابل خرج)", accountOrders:"سفارش‌های دستی/خارجی (تسویه تأییدنشده)", accountExposure:"تعهدات خارجی (خارج از مدیریت)", title:"تریدینگ‌جیم · رصدخانه", markets:"بازارها", rules:"تنظیمات ← قواعد صرافی", health:"سلامت", journal:"پژوهش / دفتر وقایع", chooseRun:"اجرای آزمایشی", lastDecisions:"۱۰۰ تصمیم آخر (برای مشاهدهٔ سفارش و نتایج باز کنید)", evidenceTitle:"شواهد اقتصادی (بدون مجوز سرمایه)",
        pair:"جفت‌ارز", bid:"خرید", ask:"فروش", spread:"اسپرد (bps)", last:"آخرین معامله", quality:"کیفیت", when:"کی می‌توانم معامله کنم؟",
        mknote:"قیمت‌ها به واحد خود صرافی است (بازارهای ریالی به تومان). حالت رصد: هیچ سفارشی ارسال نمی‌شود.",
        entry:"خرید (ورود)", exit:"فروش (خروج)", open:"باز", blocked:"مسدود", until:"تا", opens:"باز می‌شود", closes:"بسته می‌شود", noChange:"بدون تغییر تا ۷ روز",
        by:"توسط", source:"منبع", confirmed:"تأیید", quotaLeft:"سهمیهٔ باقی‌مانده", age:"سن",
        rulesTitle:"قواعد صرافی", preset:"بارگذاری الگو: تعطیلی شبانهٔ تتر/تومان، اکتبر ۲۰۲۶", export:"خروجی JSON",
        rule:"قاعده", cls:"رده / وضعیت / منبع", state:"حالت", blocksNow:"الان چه چیزی را مسدود می‌کند؟", window:"بازهٔ اعتبار",
        disable:"غیرفعال", importTitle:"ورود قواعد", importHelp:"فهرست JSON قواعد را وارد کنید. قواعد نادرست قرنطینه می‌شوند و اعمال نمی‌شوند.",
        import:"ورود", nothing:"هیچ", version:"نسخهٔ قواعد", stale:"کهنه", none:"—" },
};
let lang = localStorage.getItem("lang") || "en", view = "markets";
const $ = id => document.getElementById(id);
const t = k => T[lang][k] ?? k;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const digits = s => lang === "fa" ? String(s).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]) : String(s);
// Exact decimal strings from the API; only group the integer part, never round through float.
const num = s => { if (s == null) return t("none"); const [i, f] = String(s).split(".");
  const g = i.replace(/\B(?=(\d{3})+(?!\d))/g, ","); return digits(f ? `${g}.${f.replace(/0+$/, "") || "0"}`.replace(/\.$/, "") : g); };
const when = iso => iso ? new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB",
  { timeZone:"Asia/Tehran", weekday:"short", hour:"2-digit", minute:"2-digit", month:"short", day:"numeric" }).format(new Date(iso)) : "";
const api = (p, o = {}) => fetch(p, { ...o, headers: { "Content-Type":"application/json", "X-Gym-Token": TOKEN } })
  .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j; });

function applyLang() {
  document.documentElement.lang = lang; document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  document.querySelectorAll("[data-t]").forEach(e => e.textContent = t(e.dataset.t));
  $("lang").textContent = lang === "fa" ? "English" : "فارسی"; refresh();
}

function pill(name, a) {
  const b = a.blockers[0], nx = a.next_change;
  const head = `${t(name)}: <b>${a.allowed ? t("open") : t("blocked")}</b>`;
  const next = nx ? ` · ${a.allowed ? t("closes") : t("opens")} ${esc(when(nx))}` : ` · ${t("noChange")}`;
  const why = b ? `<div class="mut">${t("by")} ${esc(b.class)} ${esc(b.family)} “${esc(b.name)}” · ${t("source")}: ${esc(b.source)} · ${esc(b.status)}${b.confirmed ? ` · ${t("confirmed")} ${esc(when(b.confirmed))}` : ""}</div>` : "";
  const quota = a.quota_remaining != null ? `<div class="mut">${t("quotaLeft")}: ${num(a.quota_remaining)} USDT</div>` : "";
  const warn = a.warnings.map(w => `<div class="mut">⚠ ${esc(w.name)}: ${esc(w.why)}</div>`).join("");
  return `<div class="pill ${a.allowed ? (a.warnings.length ? "warn" : "ok") : "bad"}">${head}${next}${why}${quota}${warn}</div>`;
}

async function markets() {
  const d = await api("/api/markets");
  $("demo").hidden = !d.demo;
  $("fx").hidden = !d.fx && !d.universe;
  if (d.fx || d.universe) $("fx").textContent = (d.fx
    ? `USDT/IRT ${d.fx.mid ? num(d.fx.mid) : "—"} · ${d.fx.status}` : "USDT/IRT unavailable")
    + (d.universe ? ` · ${digits((d.universe.observed_assets || d.universe.selected_assets).length)} assets / ${digits(d.universe.observed_markets)} markets / ${digits(d.universe.websocket_shards || 1)} WS` : "");
  $("mk").innerHTML = d.markets.map(m => `<tr>
    <td><b>${esc(m.names[lang] || m.symbol)}</b><div class="mut">${esc(m.symbol)}</div></td>
    <td class="num">${num(m.bid)}<div class="mut">${num(m.bid_qty)}</div></td>
    <td class="num">${num(m.ask)}<div class="mut">${num(m.ask_qty)}</div></td>
    <td class="num">${num(m.spread_bps)}<div class="mut">${num(m.spread)}</div></td>
    <td class="num">${m.last_trade ? `<span class="${m.last_trade.aggressor}">${num(m.last_trade.price)}</span><div class="mut">${num(m.last_trade.qty)} · ${esc(when(m.last_trade.ts))}</div>` : t("none")}</td>
    <td>${m.flags.map(f => `<span class="flag">${esc(f)}</span>`).join("")}${m.book_age_s != null ? `<div class="mut">${t("age")} ${digits(m.book_age_s)}s</div>` : ""}</td>
    <td><div class="act">${pill("entry", m.act.entry)}${pill("exit", m.act.exit)}</div></td></tr>`).join("");
}

async function rules() {
  const d = await api("/api/rules");
  $("rv").textContent = `${t("version")} ${digits(d.version)}`;
  $("rl").innerHTML = d.rules.map(r => { const b = r.body; return `<tr>
    <td><b>${esc(b.name || b.id)}</b><div class="mut">${esc(b.id)} · ${esc(b.family)} · ${esc(b.action)}</div><div class="mut">${esc(b.note || "")}</div></td>
    <td>${esc(b.class)} / ${esc(b.status)} / ${esc(b.source)}</td>
    <td>${esc(r.state)}</td>
    <td>${r.blocks_now.length ? r.blocks_now.map(esc).join("<br>") : t("nothing")}</td>
    <td class="mut">${esc(when(b.effective_from))} → ${b.effective_until ? esc(when(b.effective_until)) : "∞"}</td>
    <td>${r.state !== "disabled" ? `<button class="btn" data-disable="${esc(b.id)}">${t("disable")}</button>` : ""}</td></tr>`; }).join("")
    + d.quarantined.map(q => `<tr><td><b>${esc(q.id)}</b></td><td colspan="5" class="SELL">QUARANTINED: ${esc(q.error)}</td></tr>`).join("");
}

async function operate() {
  const output = $("protection-state");
  try {
    const status = await api("/api/automation-safety");
    output.textContent = t("operateWarning") + "\n"
      + status.mode + " · " + status.protection + " · " + status.venue_stops
      + "\nfunded_authority=" + String(status.funded_authority)
      + " · autopilot_enabled=" + String(status.autopilot_enabled)
      + " · executor_state_verified=" + String(status.executor_state_verified);
  } catch (_) {
    output.textContent = t("operateWarning");
  }
}
$("preview-ticket").onclick = async () => {
  const out = $("ticket-output");
  try {
    const payload = JSON.parse($("offline-ticket").value);
    const preview = await api("/api/dry-run/ticket", {
      method: "POST", body: JSON.stringify(payload),
    });
    if (preview.mode !== "DRY_RUN" || preview.funded_authority !== false
        || preview.order_submitted !== false) {
      throw new Error("unsupported preview authority");
    }
    out.textContent = t("offlineTicketResult") + "\n"
      + JSON.stringify(preview, null, 2);
  } catch (_) {
    // Never echo user-provided JSON or accidental secret material in errors.
    out.textContent = t("offlineTicketError");
  }
};

async function health() {
  $("hl").textContent = JSON.stringify(await api("/api/health"), null, 2);
  const out = $("venue-facts");
  try {
    const report = await api("/api/venue-facts");
    if (report.state === "NOT_CONFIGURED") {
      out.textContent = t("venueFactsEmpty");
      return;
    }
    const capabilities = Object.entries(report.capabilities || {}).map(([name, value]) =>
      name + ": " + value.state + (value.state === "NOT_CERTIFIED" ? " · " + t("venueFactsUnverified") : ""));
    const observations = (report.facts || []).slice(0, 20).map(f =>
      f.observed_at + " · " + f.kind + " · " + f.state + " · " + f.source + " · " + f.evidence_id);
    out.textContent = t("venueFactsInfo") + "\n" + capabilities.join("\n")
      + "\n\n" + observations.join("\n");
  } catch (_) {
    out.textContent = t("venueFactsError");
  }
}

let loadedRun = "";
async function accountJournal() {
  const summary = $("account-state"), out = $("account-observations");
  try {
    const a = await api("/api/account-observations");
    if (a.state === "NOT_CONFIGURED") {
      summary.textContent = t("accountNotConfigured");
      out.textContent = "";
      return;
    }
    if (a.state !== "OBSERVED") {
      summary.textContent = t("accountError");
      out.textContent = "";
      return;
    }
    summary.textContent = t("accountObserved") + " · " + (a.observed_at || "");
    const balances = a.balances.map(x => x.asset + ": " + num(x.venue_value) + " / " + num(x.venue_locked)).join("\n");
    const orders = a.orders.map(x => x.client_id + ": " + x.raw_status + " · " + x.settlement).join("\n");
    const external = a.exposure.map(x => x.product + ": " + (x.obligation ?? t("none")) + " " + (x.obligation_asset ?? "")).join("\n");
    out.textContent = t("accountBalance") + "\n" + (balances || t("none")) + "\n\n"
      + t("accountOrders") + "\n" + (orders || t("none")) + "\n\n"
      + t("accountExposure") + "\n" + (external || t("none"));
  } catch (_) {
    summary.textContent = t("accountError");
    out.textContent = "";
  }
}
async function externalJournal() {
  const out = $("external-order-events");
  try {
    const data = await api("/api/external-order-events");
    out.textContent = data.events && data.events.length
      ? data.events.slice(-100).map(x => x.observed_at + " · " + x.account_id + " · "
          + x.client_id + " · " + x.raw_status + " · " + x.settlement
          + " (unverified)").join("\n")
      : t("externalEmpty");
  } catch (_) {
    out.textContent = t("externalReadError");
  }
}
async function journal() {
  await accountJournal();
  await externalJournal();
  const rows = await api("/api/runs"), select = $("run-select"), selected = select.value;
  const options = rows.map(r => `<option value="${esc(r.run_id)}">${esc(r.inputs.store)} · ${esc(r.inputs.symbol)} · ${esc(r.run_id)}</option>`).join("");
  if (select.innerHTML !== options) { select.innerHTML = options; if (rows.some(r => r.run_id === selected)) select.value = selected; }
  if (!select.value) { $("run-summary").textContent = t("none"); return; }
  const key = select.value + lang;
  if (loadedRun === key) return;
  const d = await api("/api/runs/" + select.value), r = d.result;
  loadedRun = key;
  $("run-summary").textContent = `${d.inputs.store.toUpperCase()} · ${r.symbol} · ${r.session?.state || "PAPER"} · ${when(d.inputs.from)} → ${when(d.inputs.to)} · ${r.quote}`;
  const curve = r.curve.map(p => Number(p[1])).filter(Number.isFinite);
  const lo = curve.reduce((a,b) => Math.min(a,b), Infinity), hi = curve.reduce((a,b) => Math.max(a,b), -Infinity);
  $("equity").innerHTML = `<title>${esc(r.quote)} · ${esc(t("journal"))}</title><polyline fill="none" stroke="currentColor" stroke-width="2" points="${curve.map((v,i) => `${i * 800 / Math.max(1,curve.length-1)},${170 - (v-lo)*160/(hi-lo || 1)}`).join(" ")}"/>`;
  $("waterfall").textContent = JSON.stringify({waterfall:r.end?.waterfall, ranking:d.ranking, baselines:d.baselines, session:r.session}, null, 2);
  $("economic").textContent = JSON.stringify({report:d.evidence, decisions:d.capital_decisions}, null, 2);
  $("decisions").innerHTML = r.decisions.slice(-100).map(x => `<details><summary>${esc(when(x.t))} · ${esc(x.action)} · ${esc(x.reasons.join("; "))}</summary><pre>${esc(JSON.stringify({...x, order:r.orders.find(o => o.ref === x.order) || null}, null, 2))}</pre></details>`).join("");
}
$("run-select").onchange = () => { loadedRun = ""; journal().catch(e => $("run-summary").textContent = e.message); };

async function refresh() {
  $("clock").textContent = `UTC ${new Date().toISOString().slice(11, 19)} · Tehran ${new Intl.DateTimeFormat("en-GB", { timeZone:"Asia/Tehran", hour:"2-digit", minute:"2-digit", second:"2-digit" }).format(new Date())}`;
  try { await ({ operate, markets, rules, health, journal })[view](); } catch (e) { console.error(e); }
}

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  view = b.dataset.view; document.querySelectorAll("nav button").forEach(x => x === b ? x.setAttribute("aria-current", "page") : x.removeAttribute("aria-current"));
  ["operate", "markets", "rules", "health", "journal"].forEach(v => $("v-" + v).hidden = v !== view); refresh();
});
$("lang").onclick = () => { lang = lang === "en" ? "fa" : "en"; localStorage.setItem("lang", lang); applyLang(); };
$("rl").onclick = async e => { const id = e.target.dataset.disable; if (id && confirm(`${t("disable")} ${id}?`)) { await api(`/api/rules/${encodeURIComponent(id)}/disable`, { method:"POST" }); rules(); } };
$("preset").onclick = async () => { await api("/api/presets/usdt-irt-october-2026", { method:"POST" }); rules(); };
$("doimp").onclick = async () => {
  try { const r = await api("/api/rules/import", { method:"POST", body: $("imp").value });
    $("impres").textContent = `${r.imported} imported, ${r.quarantined.length} quarantined`; rules(); }
  catch (e) { $("impres").textContent = e.message; }
};
$("demo").hidden = !DEMO;
applyLang(); setInterval(refresh, 2000);
