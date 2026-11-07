/* Shared cash replay uses native records, separately from independent comparisons. */
window.gymPortfolio = (() => {
  let language, setup, record, busy = false;
  const $ = id => document.getElementById(id);
  const inputs = ['portfolio-symbols', 'portfolio-from', 'portfolio-to', 'portfolio-resolution', 'portfolio-cash', 'portfolio-fee', 'portfolio-strategy', 'portfolio-params'];
  function mount({api, esc, table, keyValues, amount, when, curveFigure}) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (next === language || busy) return;
    const saved = language ? Object.fromEntries(inputs.map(id => [id, $(id).value])) : {};
    language = next;
    const fa = next === 'fa', text = (en, persian) => fa ? persian : en;
    const field = (id, title, attrs = '') => `<label for="${id}">${title}<input id="${id}" class="input" dir="ltr" ${attrs}></label>`;
    $('portfolio-workbench').innerHTML = `<h2>${text('Shared-cash portfolio replay', 'بازپخش سبد با موجودی مشترک')}</h2>
      <p class="field-help">${text('One strategy, 2–8 distinct base assets and one quote currency. Each entry targets an equal share of the available portfolio equity. Paper only; no orders are sent. Gaps and stale marks can hide losses.', 'یک راهبرد، ۲ تا ۸ دارایی پایهٔ متفاوت و یک ارز مظنه. سهم هدف هر ورود از ارزش سبد برابر است. فقط آزمایشی؛ سفارشی ارسال نمی‌شود. شکاف داده و قیمت کهنه می‌تواند زیان را پنهان کند.')}</p>
      <button id="portfolio-load" type="button" class="button">${text('Load observed markets and saved portfolios', 'دریافت بازارهای مشاهده‌شده و سبدهای ذخیره‌شده')}</button>
      <form id="portfolio-form"><fieldset id="portfolio-fields" disabled><legend>${text('Historical replay · UTC · at most 31 days', 'بازپخش تاریخی · UTC · حداکثر ۳۱ روز')}</legend><div class="ticket-fields">
      ${field('portfolio-symbols', text('Markets · comma separated · same quote currency', 'بازارها · جداشده با ویرگول · ارز مظنهٔ یکسان'), 'required list="portfolio-markets" autocomplete="off"')}<datalist id="portfolio-markets"></datalist>
      ${field('portfolio-from', text('From · UTC', 'از · UTC'), 'required type="datetime-local" step="1"')}
      ${field('portfolio-to', text('To · UTC · exclusive', 'تا · UTC · غیرشامل'), 'required type="datetime-local" step="1"')}
      <label for="portfolio-resolution">${text('Decision close', 'بازهٔ تصمیم')}<select id="portfolio-resolution" dir="ltr"></select></label>
      ${field('portfolio-cash', text('Starting shared cash · quote units', 'موجودی اولیهٔ مشترک · واحد مظنه'), 'required inputmode="decimal" value="1000"')}
      ${field('portfolio-fee', text('Fee per fill · fraction', 'کارمزد هر اجرا · کسر'), 'required inputmode="decimal" value="0.001"')}
      <label for="portfolio-strategy">${text('Strategy', 'راهبرد')}<select id="portfolio-strategy" dir="ltr"></select></label>
      <label for="portfolio-params">${text('Strategy parameters · JSON object', 'پارامترهای راهبرد · شیء JSON')}<textarea id="portfolio-params" class="input code" dir="ltr" rows="3" spellcheck="false" required>{}</textarea></label>
      </div><p class="field-help">${text('Market fills, 500 ms latency, point-in-time rules. Starting cash is denominated in the selected markets’ common quote currency.', 'اجرای بازار، تأخیر ۵۰۰ میلی‌ثانیه و قواعد معتبر در همان زمان. موجودی اولیه برحسب ارز مظنهٔ مشترک بازارهای انتخابی است.')}</p><button id="portfolio-submit" class="button" type="submit">${text('Run shared-cash replay', 'اجرای بازپخش سبد')}</button></fieldset></form>
      <p id="portfolio-status" role="status" aria-live="polite"></p><div id="portfolio-saved"></div><div id="portfolio-result"></div>`;
    const call = (action, value = null) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, action === 'portfolio-replay' ? 135000 : 10000);
    const controls = () => { $('portfolio-load').disabled = busy; $('portfolio-fields').disabled = busy || !setup; };
    async function act(work) {
      if (busy) return;
      busy = true; controls(); $('portfolio-status').textContent = text('Working…', 'در حال اجرا…');
      try { await work(); $('portfolio-status').textContent = text('Request completed.', 'درخواست انجام شد.'); }
      catch { $('portfolio-status').textContent = text('Request failed. Check distinct observed markets, common quote, dates, cash and strategy parameters. Inspect saved portfolios before retrying; the calculation may have saved a result.', 'درخواست ناموفق بود. بازارهای متمایز، ارز مظنهٔ مشترک، تاریخ‌ها، موجودی و پارامترها را بررسی کنید. پیش از تکرار سبدهای ذخیره‌شده را بخوانید؛ ممکن است نتیجه ثبت شده باشد.'); }
      finally { busy = false; controls(); if (document.documentElement.lang !== language) mount({api, esc, table, keyValues, amount, when, curveFigure}); }
    }
    function fillSetup() {
      if (!setup) return;
      $('portfolio-markets').innerHTML = setup.symbols.map(s => `<option value="${esc(s)}"></option>`).join('');
      $('portfolio-resolution').innerHTML = setup.resolutions.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
      $('portfolio-strategy').innerHTML = setup.strategies.map(s => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join('');
      $('portfolio-resolution').value = setup.defaults.resolution;
      $('portfolio-fee').value = setup.defaults.fee_rate;
    }
    async function savedRuns() {
      const data = await call('portfolio-list');
      $('portfolio-saved').innerHTML = table([text('Saved portfolios · latest 100', 'سبدهای ذخیره‌شده · ۱۰۰ مورد آخر'), text('Markets', 'بازارها'), text('End', 'پایان')], data.runs.map(row => [
        `<button type="button" class="button button-small" data-portfolio="${esc(row.run_id)}">${esc(row.run_id)}</button>`, esc(row.inputs.symbols.join(', ')), esc(when(row.inputs.to))]));
      $('portfolio-saved').querySelectorAll('[data-portfolio]').forEach(button => { button.onclick = () => act(async () => { record = await call('portfolio-read', {run_id: button.dataset.portfolio}); render(); }); });
    }
    function render() {
      if (!record) return;
      const result = record.result, end = result.end;
      $('portfolio-result').innerHTML = `<h3>${esc(record.run_id)} · ${esc(result.quote)}</h3>` + keyValues([
        [text('Equity · recorded bid marks', 'ارزش · قیمت خرید ثبت‌شده'), amount(end.equity)], [text('Net', 'خالص'), amount(end.net)],
        [text('Return · %', 'بازده · درصد'), amount(record.performance?.total_return_pct)],
        [text('Drawdown · sampled %', 'افت · درصد نمونه‌برداری‌شده'), amount(record.performance?.max_drawdown_pct)]]) + curveFigure(result) + table(
        [text('Market', 'بازار'), text('Fills', 'اجراها'), text('Closed trades', 'معاملات بسته'), text('Realized P/L', 'سود و زیان محقق'), text('Held · base units', 'دارایی · واحد پایه'), text('Last recorded bid', 'آخرین قیمت خرید ثبت‌شده')],
        Object.entries(result.markets).map(([s, row]) => [esc(s), esc(row.fills), esc(row.closed_trades), amount(row.realized_pnl), amount(row.holding), amount(row.last_bid)])) +
        `<details><summary>${text('Verified inputs, orders and exact balances', 'ورودی، سفارش و موجودی دقیق بررسی‌شده')}</summary><pre class="output" dir="ltr">${esc(JSON.stringify(record, null, 2))}</pre></details>`;
    }
    $('portfolio-load').onclick = () => act(async () => {
      const data = await api('/api/research');
      if (!Array.isArray(data?.symbols) || !Array.isArray(data.resolutions) || !Array.isArray(data.strategies) || !data.defaults) throw new Error('Invalid research setup');
      setup = data; fillSetup(); await savedRuns();
    });
    $('portfolio-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      const result = await call('portfolio-replay', {symbols: $('portfolio-symbols').value.split(',').map(s => s.trim().toUpperCase()),
        from: $('portfolio-from').value + 'Z', to: $('portfolio-to').value + 'Z', resolution: $('portfolio-resolution').value,
        cash: $('portfolio-cash').value, strategy: $('portfolio-strategy').value, params: JSON.parse($('portfolio-params').value),
        rules_mode: 'point-in-time', cost: {fee_rate: $('portfolio-fee').value, latency_ms: 500, max_wait_s: 60, fee_assumption: 'fee-in-received-asset'}});
      record = await call('portfolio-read', {run_id: result.run_id}); render(); await savedRuns();
    }); };
    fillSetup(); for (const [id, value] of Object.entries(saved)) $(id).value = value;
    controls(); render();
  }
  return {mount};
})();
