"use strict";
// Paper charts: SVG geometry stretched to the container, HTML text, pointer and keyboard read-outs.
// Loaded before app.js; helpers such as t(), esc() and when() are called only at render time.
// Geometry stays in a stretched SVG; text lives in HTML so it never scales or clips at any width.
const tick = value => new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-GB", Math.abs(value) >= 1e6
  ? { notation: "compact", maximumFractionDigits: 2 } : { maximumFractionDigits: 2 }).format(value);
const chartData = new Map();  // chart id -> points with x in viewBox units, for the read-out
let chartCount = 0;
function chartPoints(curve) {
  return list(curve).filter(point => Array.isArray(point) && point.length > 1 && point[1] != null && point[1] !== "" && Number.isFinite(Number(point[1])) && Number.isFinite(Date.parse(point[0])))
    .map(point => ({ t: point[0], ms: Date.parse(point[0]), raw: String(point[1]), v: Number(point[1]) }));
}
function placeX(points, first, last) {
  for (const [i, point] of points.entries())
    point.x = 640 * (last > first && Number.isFinite(point.ms) ? (point.ms - first) / (last - first) : i / Math.max(1, points.length - 1));
}
const polyline = (points, y) => points.map(point => `${point.x.toFixed(2)},${y(point.v).toFixed(2)}`).join(" ");
function curveFigure(result) {
  const points = chartPoints(result.curve);
  if (!points.length) return empty(t("noCurve"));
  const values = points.map(point => point.v), lo = Math.min(...values), hi = Math.max(...values);
  const first = points[0].ms, last = points[points.length - 1].ms;
  placeX(points, first, last);
  const y = value => hi === lo ? 88 : 6 + (hi - value) * 164 / (hi - lo);
  const coordinates = polyline(points, y);
  const key = JSON.stringify([result.quote || "", points.map(point => [point.t, point.raw])]);
  const id = [...chartData].find(([, data]) => data.key === key)?.[0] || `chart-${++chartCount}`;
  if (!chartData.has(id) && chartData.size >= 40) chartData.delete(chartData.keys().next().value);
  chartData.set(id, { key, points, quote: result.quote || "" });
  // Underwater: distance below the running peak, so the depth and length of each loss are visible.
  let peak = -Infinity;
  const under = points.map(point => { peak = Math.max(peak, point.v); return { ...point, v: peak > 0 ? point.v / peak - 1 : 0 }; });
  const worst = Math.min(0, ...under.map(point => point.v));
  const dy = value => worst === 0 ? 4 : 4 + value / worst * 52;
  const markers = list(result.orders).filter(order => order.status === "FILLED" && Number.isFinite(Date.parse(order.fill_time)) && last > first)
    .map(order => { const left = Math.min(100, Math.max(0, (Date.parse(order.fill_time) - first) / (last - first) * 100));
      return `<span class="chart-marker ${order.side === "BUY" ? "buy" : "sell"}" style="left:${left.toFixed(2)}%" title="${esc(`${order.side} ${order.qty} @ ${order.price} · ${when(order.fill_time)}`)}"></span>`; }).join("");
  const from = when(points[0].t, true), to = when(points[points.length - 1].t, true);
  const title = `${t("equityCurve")} · ${result.quote || ""} · ${tick(lo)} – ${tick(hi)} · ${from} → ${to}`;
  return `<figure class="equity-figure"><div class="chart-frame" dir="ltr"><div class="chart-y" aria-hidden="true"><span>${esc(tick(hi))}</span><span>${esc(tick(lo))}</span></div>
    <svg class="chart" data-chart="${id}" tabindex="0" viewBox="0 0 640 176" preserveAspectRatio="none" role="img" aria-label="${esc(title + " · " + t("chartKeys"))}"><title>${esc(title)}</title>
    <line class="chart-base" x1="0" y1="6" x2="640" y2="6"/><line class="chart-base" x1="0" y1="170" x2="640" y2="170"/>
    <polygon class="chart-area" points="0,170 ${coordinates} 640,170"/><polyline class="chart-line" points="${coordinates}" fill="none"/>
    <line class="chart-cursor" x1="0" y1="0" x2="0" y2="176"/></svg>
    <div class="chart-overlay"><span aria-hidden="true">${markers}</span><output class="chart-tip" hidden></output></div>
    <div class="chart-y under-y" aria-hidden="true"><span>0 %</span><span>${esc(digits((worst * 100).toFixed(1)))} %</span></div>
    <svg class="chart underwater" viewBox="0 0 640 60" preserveAspectRatio="none" role="img" aria-label="${esc(`${t("underwater")} · ${digits((worst * 100).toFixed(2))} %`)}">
    <polygon class="chart-area neg" points="0,4 ${polyline(under, dy)} 640,4"/><line class="chart-base" x1="0" y1="4" x2="640" y2="4"/></svg>
    <div class="chart-x" aria-hidden="true"><span>${esc(from)}</span><span>${esc(result.quote || "")}</span><span>${esc(to)}</span></div></div>
    <figcaption class="field-help">${esc(t("curveNote"))}</figcaption></figure>`;
}
// Several equity paths on one axis, each as a return from its own start so different cash compares.
function overlayFigure(series) {
  const usable = series.map(item => ({ ...item, points: chartPoints(item.curve) })).filter(item => item.points.length > 1);
  if (usable.length < 2) return "";
  for (const item of usable) { const base = item.points[0].v; for (const point of item.points) point.v = base ? point.v / base - 1 : 0; }
  const all = usable.flatMap(item => item.points), first = Math.min(...all.map(p => p.ms)), last = Math.max(...all.map(p => p.ms));
  const lo = Math.min(0, ...all.map(p => p.v)), hi = Math.max(0, ...all.map(p => p.v));
  const y = value => 6 + (hi - value) * 164 / (hi - lo || 1);
  for (const item of usable) placeX(item.points, first, last);
  const points = [...new Set(all.map(point => point.ms))].sort((a, b) => a - b).map(ms => ({ms, t: new Date(ms).toISOString()}));
  placeX(points, first, last);
  const key = JSON.stringify(usable.map(item => [item.name, item.points.map(point => [point.t, point.raw])]));
  const id = [...chartData].find(([, data]) => data.key === key)?.[0] || `chart-${++chartCount}`;
  if (!chartData.has(id) && chartData.size >= 40) chartData.delete(chartData.keys().next().value);
  chartData.set(id, {key, points, series: usable});
  return `<figure class="equity-figure"><div class="chart-frame" dir="ltr"><div class="chart-y" aria-hidden="true"><span>${esc(digits((hi * 100).toFixed(1)))} %</span><span>${esc(digits((lo * 100).toFixed(1)))} %</span></div>
    <svg class="chart" data-chart="${id}" tabindex="0" viewBox="0 0 640 176" preserveAspectRatio="none" role="img" aria-label="${esc(t("overlayTitle") + " · " + usable.map(item => item.name).join(", ") + ' · ' + t('chartKeys'))}">
    <line class="chart-base" x1="0" y1="${y(0)}" x2="640" y2="${y(0)}"/>${usable.map((item, i) => `<polyline class="chart-line series-${i % 4}" points="${polyline(item.points, y)}" fill="none"/>`).join("")}<line class="chart-cursor" x1="0" y1="0" x2="0" y2="176"/></svg>
    <div class="chart-overlay"><output class="chart-tip" hidden></output></div>
    <div class="chart-x" aria-hidden="true"><span>${esc(when(new Date(first).toISOString(), true))}</span><span>${esc(when(new Date(last).toISOString(), true))}</span></div></div>
    <figcaption class="chart-legend">${usable.map((item, i) => `<span class="series-${i % 4}">${esc(item.name)}</span>`).join("")}</figcaption><p class="field-help">${esc(t('overlayInspectionNote'))}</p></figure>`;
}
function showCursor(svg, index) {
  const data = chartData.get(svg.dataset.chart);
  if (!data) return;
  const point = data.points[Math.max(0, Math.min(data.points.length - 1, index))];
  svg.dataset.cursor = data.points.indexOf(point);
  const cursor = svg.querySelector(".chart-cursor"), tip = svg.parentElement.querySelector(".chart-tip");
  cursor.setAttribute("x1", point.x); cursor.setAttribute("x2", point.x); svg.classList.add("tracking");
  tip.hidden = false;
  tip.textContent = data.series ? `${when(point.t)} · ` + data.series.map(item => {
    const exact = item.points.find(row => row.ms === point.ms);
    return `${item.name}: ${exact ? digits((exact.v * 100).toFixed(4)) + ' %' : t('unavailable')}`;
  }).join(' · ') : `${when(point.t)} · ${num(point.raw)} ${data.quote}`;
  tip.style.left = `${Math.max(0, Math.min(100, point.x / 6.4)).toFixed(2)}%`;
  tip.style.transform = point.x < 128 ? 'translateX(0)' : point.x > 512 ? 'translateX(-100%)' : 'translateX(-50%)';
}
function hideCursor(svg) {
  svg.classList.remove("tracking");
  const tip = svg.parentElement?.querySelector(".chart-tip");
  if (tip) tip.hidden = true;
}
let trackedChart = null;
document.addEventListener("pointermove", event => {
  const svg = event.target.closest?.("svg[data-chart]");
  if (trackedChart && trackedChart !== svg) hideCursor(trackedChart);
  trackedChart = svg || null;
  if (!svg) return;
  const data = chartData.get(svg.dataset.chart), box = svg.getBoundingClientRect();
  if (!data || !box.width) return;
  const x = (event.clientX - box.left) / box.width * 640;
  let best = 0;
  for (const [i, point] of data.points.entries()) if (Math.abs(point.x - x) < Math.abs(data.points[best].x - x)) best = i;
  showCursor(svg, best);
});
document.addEventListener("keydown", event => {
  const svg = event.target.closest?.("svg[data-chart]");
  const data = svg && chartData.get(svg.dataset.chart);
  if (!data) return;
  const at = Number(svg.dataset.cursor ?? -1), step = { ArrowRight: 1, ArrowLeft: -1, PageUp: 10, PageDown: -10 }[event.key];
  const index = event.key === "Home" ? 0 : event.key === "End" ? data.points.length - 1 : step ? (at < 0 ? 0 : at + step) : null;
  if (index === null) return;
  event.preventDefault();
  showCursor(svg, index);
});
document.addEventListener("focusout", event => { if (event.target.matches?.("svg[data-chart]")) hideCursor(event.target); });
function waterfallFigure(entries, quote) {
  if (!entries.length || entries.some(([, value]) => !Number.isFinite(Number(value)))) return "";
  let accumulated = 0;
  const steps = entries.map(([key, value]) => {
    const start = key === "net" ? 0 : accumulated;
    const end = start + Number(value);
    if (key !== "net") accumulated = end;
    return { key, start, end, value: Number(value) };
  });
  const low = Math.min(0, ...steps.flatMap(step => [step.start, step.end]));
  const high = Math.max(0, ...steps.flatMap(step => [step.start, step.end]));
  const y = value => 6 + (high - value) * 164 / (high - low || 1);
  const width = steps.length * 100;
  return `<figure class="equity-figure"><svg class="chart waterfall-chart" viewBox="0 0 ${width} 176" preserveAspectRatio="none" role="img" aria-label="${esc(t("costWaterfall") + " · " + quote)}"><title>${esc(t("costWaterfall"))}</title>
    <line class="chart-base" x1="0" y1="${y(0)}" x2="${width}" y2="${y(0)}"/>${steps.map((step, i) => {
    const top = Math.min(y(step.start), y(step.end)), height = Math.max(1, Math.abs(y(step.start) - y(step.end)));
    return `<rect x="${i * 100 + 18}" y="${top}" width="64" height="${height}" class="waterfall-bar ${step.value < 0 ? "neg" : "pos"}"/>`;
  }).join("")}</svg><div class="waterfall-labels" dir="ltr" style="grid-template-columns:repeat(${steps.length},minmax(0,1fr))">${steps.map(step =>
    `<span><strong class="${step.value < 0 ? "neg" : "pos"}" dir="ltr">${esc(tick(step.value))}</strong><small>${label(step.key)}</small></span>`).join("")}</div></figure>`;
}
