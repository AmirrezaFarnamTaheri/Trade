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
    const x = p => 80 + 610 * (p.t - first) / (last - first || 1);
    const y = p => 175 - 135 * (p.price - low) / (high - low || 1);
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
      return `<circle class="replay-point" cx="${x(p)}" cy="${y(p)}" r="${p.row.index === selected ? 6 : 3}" data-replay-index="${p.row.index}" role="button" tabindex="0" aria-label="${esc(title)}" aria-current="${p.row.index === selected ? 'step' : 'false'}"><title>${esc(title)}</title></circle>`;
    }).join('');
    const note = fa ? 'فقط نقاط ثبت‌شده؛ خط روی فاصله‌های نامعلوم رسم نمی‌شود. برای انتخاب، کلیک یا Enter بزنید؛ کلیدهای جهت تصمیم را عوض می‌کنند.' : 'Recorded points only; unknown gaps are not connected. Click or press Enter to select; arrow keys move between decisions.';
    const caption = 'replay-chart-caption-' + metric.replace(/[^a-z0-9_-]/gi, '_');
    return `<figure class="equity-figure"><svg class="chart replay-chart" viewBox="0 0 720 225" role="group" aria-label="${esc(label)}" aria-describedby="${caption}" dir="ltr"><title>${esc(label)}</title><text x="5" y="40">${esc(String(high))}</text><text x="5" y="175">${esc(String(low))}</text>${paths}${markers}<text x="80" y="212">${esc(points[0].row.known_at_decision.t)}</text><text x="80" y="18">${esc(label)} · ${metric === 'price' || metric === 'equity' ? esc(quote) : ''}</text></svg><figcaption id="${caption}" class="field-help">${esc(note)}</figcaption></figure>`;
  }
  return {render};
})();
