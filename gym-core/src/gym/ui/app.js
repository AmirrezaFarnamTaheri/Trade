const { token: TOKEN, demo: DEMO } = JSON.parse(document.getElementById("gym-config").textContent);
const T = {
  en: { title:"TradingGYM · Observatory", markets:"Markets", rules:"Settings → Venue rules", health:"Health", journal:"Research / Journal", chooseRun:"Paper run", lastDecisions:"Last 100 decisions (expand for marks and order)", evidenceTitle:"Economic evidence (no capital authority)",
        pair:"Pair", bid:"Bid", ask:"Ask", spread:"Spread (bps)", last:"Last trade", quality:"Quality", when:"When can I act?",
        mknote:"Prices are the venue's own quote units (IRT legs in toman, unit epoch 1). Observatory mode: no orders are ever sent.",
        entry:"Buy (entry)", exit:"Sell (exit)", open:"open", blocked:"blocked", until:"until", opens:"opens", closes:"closes", noChange:"no change in 7 days",
        by:"by", source:"source", confirmed:"confirmed", quotaLeft:"quota left", age:"age",
        rulesTitle:"Venue rules", preset:"Load preset: USDT/IRT night closure, October 2026", export:"Export JSON",
        rule:"Rule", cls:"Class / status / source", state:"State", blocksNow:"What does this block right now?", window:"Effective",
        disable:"Disable", importTitle:"Import rules", importHelp:"Paste a JSON list of rules. Malformed rules are quarantined, never applied.",
        import:"Import", nothing:"nothing", version:"rule set version", stale:"stale", none:"—" },
  fa: { title:"تریدینگ‌جیم · رصدخانه", markets:"بازارها", rules:"تنظیمات ← قواعد صرافی", health:"سلامت", journal:"پژوهش / دفتر وقایع", chooseRun:"اجرای آزمایشی", lastDecisions:"۱۰۰ تصمیم آخر (برای مشاهدهٔ سفارش و نتایج باز کنید)", evidenceTitle:"شواهد اقتصادی (بدون مجوز سرمایه)",
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
  $("fx").hidden = !d.fx;
  if (d.fx) $("fx").textContent = `USDT/IRT ${d.fx.mid ? num(d.fx.mid) : "—"} · ${d.fx.status}`;
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

async function health() { $("hl").textContent = JSON.stringify(await api("/api/health"), null, 2); }

let loadedRun = "";
async function journal() {
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
  $("waterfall").textContent = JSON.stringify({waterfall:r.end?.waterfall, baselines:d.baselines, session:r.session}, null, 2);
  $("economic").textContent = JSON.stringify({report:d.evidence, decisions:d.capital_decisions}, null, 2);
  $("decisions").innerHTML = r.decisions.slice(-100).map(x => `<details><summary>${esc(when(x.t))} · ${esc(x.action)} · ${esc(x.reasons.join("; "))}</summary><pre>${esc(JSON.stringify({...x, order:r.orders.find(o => o.ref === x.order) || null}, null, 2))}</pre></details>`).join("");
}
$("run-select").onchange = () => { loadedRun = ""; journal().catch(e => $("run-summary").textContent = e.message); };

async function refresh() {
  $("clock").textContent = `UTC ${new Date().toISOString().slice(11, 19)} · Tehran ${new Intl.DateTimeFormat("en-GB", { timeZone:"Asia/Tehran", hour:"2-digit", minute:"2-digit", second:"2-digit" }).format(new Date())}`;
  try { await ({ markets, rules, health, journal })[view](); } catch (e) { console.error(e); }
}

document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  view = b.dataset.view; document.querySelectorAll("nav button").forEach(x => x === b ? x.setAttribute("aria-current", "page") : x.removeAttribute("aria-current"));
  ["markets", "rules", "health", "journal"].forEach(v => $("v-" + v).hidden = v !== view); refresh();
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
