window.GymReplayChart = (() => {
  function render(rows, selected, quote, esc, fa, metric = 'price') {
    const label = metric === 'price' ? (fa ? 'تاریخچهٔ تصمیم تا نقطهٔ انتخاب‌شده' : 'Decision history through the selected point')
      : metric === 'equity' ? (fa ? 'ارزش آزمایشی پیش از تصمیم' : 'Modeled equity before decision') : metric;
    const value = row => metric === 'price' ? row.known_at_decision.close : metric === 'equity' ? row.equity_before_decision : row.known_at_decision.feature_values?.[metric];
    const points = rows.filter(row => row.index <= selected).map(row => ({
      row, t: Date.parse(row.known_at_decision.t), raw: value(row), price: Number(value(row)),
    })).filter(p => p.raw != null && typeof p.raw !== 'boolean' && Number.isFinite(p.t) && Number.isFinite(p.price) && (metric !== 'price' || p.price > 0));
    if (!points.length) return `<p>${esc(label)}: ${fa ? 'مقدار عددی ثبت نشده است.' : 'No recorded numeric values.'}</p>`;
    const low = Math.min(...points.map(p => p.price)), high = Math.max(...points.map(p => p.price));
    const first = points[0].t, last = points.at(-1).t;
    const x = p => 10 + 620 * (p.t - first) / (last - first || 1);
    const y = p => 170 - 160 * (p.price - low) / (high - low || 1);
    let previous = null;
    const paths = points.map(p => {
      const end = previous?.row.known_at_decision.bar_known?.end;
      const adjoining = end != null && end === p.row.known_at_decision.bar_known?.start;
      const segment = adjoining ? `<path class="chart-line" d="M${x(previous)},${y(previous)} L${x(p)},${y(p)}"/>` : '';
      previous = p;
      return segment;
    }).join('');
    const markers = points.map(p => {
      const known = p.row.known_at_decision;
      const title = `${known.t} · ${known.action} · ${p.raw} ${metric === 'price' || metric === 'equity' ? quote : metric}`;
      return `<g class="replay-target" data-replay-index="${p.row.index}" role="button" tabindex="0" aria-label="${esc(title)}" aria-current="${p.row.index === selected ? 'step' : 'false'}"><title>${esc(title)}</title><rect x="${x(p)-24}" y="${y(p)-24}" width="48" height="48" fill="transparent"/><circle class="replay-point" cx="${x(p)}" cy="${y(p)}" r="${p.row.index === selected ? 6 : 3}"/></g>`;
    }).join('');
    const note = fa ? 'فقط نقاط ثبت‌شده؛ خط روی فاصله‌های نامعلوم رسم نمی‌شود. برای انتخاب، کلیک یا Enter بزنید؛ کلیدهای جهت تصمیم را عوض می‌کنند.' : 'Recorded points only; unknown gaps are not connected. Click or press Enter to select; arrow keys move between decisions.';
    const caption = 'replay-chart-caption-' + metric.replace(/[^a-z0-9_-]/gi, '_');
    const format = value => new Intl.NumberFormat(fa ? 'fa-IR' : 'en-GB', {maximumSignificantDigits: 5, notation: Math.abs(value) >= 1000000 ? 'compact' : 'standard'}).format(value);
    return `<figure class="equity-figure"><p class="field-help">${esc(label)} · ${metric === 'price' || metric === 'equity' ? esc(quote) : ''}</p><div class="chart-frame replay-frame" dir="ltr"><div class="chart-y" aria-hidden="true"><span>${esc(format(high))}</span><span>${esc(format(low))}</span></div><svg class="chart replay-chart" viewBox="0 0 640 180" preserveAspectRatio="none" role="group" aria-label="${esc(label)}" aria-describedby="${caption}"><title>${esc(label)}</title>${paths}${markers}</svg><div class="chart-x"><span>${esc(points[0].row.known_at_decision.t)}</span><span>${esc(points.at(-1).row.known_at_decision.t)}</span></div></div><figcaption id="${caption}" class="field-help">${esc(note)}</figcaption></figure>`;
  }
  return {render};
})();
