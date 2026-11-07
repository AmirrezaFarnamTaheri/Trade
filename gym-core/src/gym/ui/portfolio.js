/* Shared cash replay uses native records, separately from independent comparisons. */
window.gymPortfolio = (() => {
  let language, setup, record, checkpoint, busy = false;
  const $ = id => document.getElementById(id);
  const inputs = ['portfolio-symbols', 'portfolio-from', 'portfolio-to', 'portfolio-resolution', 'portfolio-cash', 'portfolio-fee', 'portfolio-strategy', 'portfolio-params', 'portfolio-weighting', 'portfolio-lookback', 'portfolio-cap', 'portfolio-drawdown', 'portfolio-daily-loss', 'portfolio-buffer', 'portfolio-clock', 'portfolio-correlation', 'portfolio-group-cap', 'portfolio-rebalance', 'portfolio-threshold'];
  function mount({api, esc, table, keyValues, amount, when, curveFigure, strategyFields}) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (next === language || busy) return;
    const saved = language ? Object.fromEntries(inputs.map(id => [id, $(id).value])) : {};
    language = next;
    const fa = next === 'fa', text = (en, persian) => fa ? persian : en;
    const field = (id, title, attrs = '') => `<label for="${id}">${title}<input id="${id}" class="input" dir="ltr" ${attrs}></label>`;
    $('portfolio-workbench').innerHTML = `<h2>${text('Shared-cash portfolio replay', 'بازپخش سبد با موجودی مشترک')}</h2>
      <p class="field-help">${text('One strategy, 2–500 distinct base assets and one quote currency. Entries use the selected allocation policy against shared portfolio equity. Paper only; no orders are sent. Gaps and stale marks can hide losses.', 'یک راهبرد، ۲ تا ۵۰۰ دارایی پایهٔ متفاوت و یک ارز مظنه. وزن ورود از سیاست تخصیص انتخابی و ارزش مشترک سبد می‌آید. فقط آزمایشی؛ سفارشی ارسال نمی‌شود. شکاف داده و قیمت کهنه می‌تواند زیان را پنهان کند.')}</p>
      <button id="portfolio-load" type="button" class="button">${text('Load observed markets and saved portfolios', 'دریافت بازارهای مشاهده‌شده و سبدهای ذخیره‌شده')}</button>
      <form id="portfolio-form"><fieldset id="portfolio-fields" disabled><legend>${text('Historical replay · UTC · at most 31 days', 'بازپخش تاریخی · UTC · حداکثر ۳۱ روز')}</legend><div class="ticket-fields">
      ${field('portfolio-symbols', text('Markets · comma separated · same quote currency', 'بازارها · جداشده با ویرگول · ارز مظنهٔ یکسان'), 'required list="portfolio-markets" autocomplete="off"')}<datalist id="portfolio-markets"></datalist>
      <div><p class="field-help">${text('Use the whole observed quote universe, or edit a subset above.', 'همهٔ بازارهای مشاهده‌شدهٔ یک مظنه را انتخاب کنید یا زیرمجموعه را در بالا ویرایش کنید.')}</p><button id="portfolio-all-usdt" class="button" type="button">${text('All USDT markets', 'همهٔ بازارهای تتر')}</button> <button id="portfolio-all-tmn" class="button" type="button">${text('All TMN markets', 'همهٔ بازارهای تومان')}</button></div>
      ${field('portfolio-from', text('From · UTC', 'از · UTC'), 'required type="datetime-local" step="1"')}
      ${field('portfolio-to', text('To · UTC · exclusive', 'تا · UTC · غیرشامل'), 'required type="datetime-local" step="1"')}
      <label for="portfolio-resolution">${text('Decision close', 'بازهٔ تصمیم')}<select id="portfolio-resolution" dir="ltr"></select></label>
      ${field('portfolio-cash', text('Starting shared cash · quote units', 'موجودی اولیهٔ مشترک · واحد مظنه'), 'required inputmode="decimal" value="1000"')}
      ${field('portfolio-fee', text('Fee per fill · fraction', 'کارمزد هر اجرا · کسر'), 'required inputmode="decimal" value="0.001"')}
      <label for="portfolio-strategy">${text('Strategy', 'راهبرد')}<select id="portfolio-strategy" dir="ltr"></select></label>
      <div id="portfolio-strategy-fields" class="ticket-fields"></div><details class="disclosure"><summary>${text('Advanced strategy parameters', 'پارامترهای پیشرفته راهبرد')}</summary><label for="portfolio-params">${text('Exact parameters · JSON object', 'پارامترهای دقیق · شیء JSON')}<textarea id="portfolio-params" class="input code" dir="ltr" rows="3" spellcheck="false" required>{}</textarea></label></details>
      </div><details class="disclosure"><summary>${text('Allocation and portfolio risk', 'تخصیص و ریسک سبد')}</summary><div class="ticket-fields">
      <label for="portfolio-weighting">${text('Entry weighting', 'وزن ورود')}<select id="portfolio-weighting"><option value="equal">${text('Equal', 'برابر')}</option><option value="inverse-volatility">${text('Inverse volatility', 'معکوس نوسان')}</option><option value="risk-parity">${text('Equal risk contribution', 'سهم ریسک برابر')}</option></select></label>
      ${field('portfolio-lookback', text('Closed return intervals', 'بازه‌های بازده بسته'), 'type="number" min="3" max="500" value="20"')}
      ${field('portfolio-cap', text('Maximum weight · fraction', 'بیشینه وزن · کسر'), 'inputmode="decimal" value="1"')}
      ${field('portfolio-drawdown', text('Drawdown limit · fraction · optional', 'حد افت · کسر · اختیاری'), 'inputmode="decimal"')}
      ${field('portfolio-daily-loss', text('Tehran daily loss limit · fraction · optional', 'حد زیان روز تهران · کسر · اختیاری'), 'inputmode="decimal"')}
      ${field('portfolio-buffer', text('Cash buffer · fraction', 'ذخیره نقد · کسر'), 'inputmode="decimal" value="0"')}
      ${field('portfolio-clock', text('Target refresh · seconds', 'بازبینی هدف · ثانیه'), 'type="number" min="60" max="604800" value="60"')}
      ${field('portfolio-correlation', text('Correlation threshold · optional', 'آستانه همبستگی · اختیاری'), 'inputmode="decimal"')}
      ${field('portfolio-group-cap', text('Correlated group weight cap · fraction', 'سقف وزن گروه همبسته · کسر'), 'inputmode="decimal" value="1"')}
      <label for="portfolio-rebalance">${text('Rebalance existing holdings', 'بازتنظیم دارایی‌های موجود')}<select id="portfolio-rebalance"><option value="false">${text('Off · entries only', 'خاموش · فقط ورودها')}</option><option value="true">${text('On · modeled buys and sells', 'روشن · خرید و فروش مدل‌شده')}</option></select></label>
      ${field('portfolio-threshold', text('Minimum rebalance drift · equity fraction', 'حداقل انحراف بازتنظیم · کسر ارزش سبد'), 'inputmode="decimal" value="0.01"')}
      </div><p class="field-help">${text('Weights use aligned past closed returns and apply to subsequent entries. Dynamic weights require sufficient continuous aligned history. Risk limits cancel pending entries and request exits at the next decision; gaps and closures can exceed the limit.', 'وزن‌ها از بازده‌های بستهٔ گذشته محاسبه و برای ورودهای بعدی اعمال می‌شوند. وزن پویا به سابقه پیوسته و هم‌زمان کافی نیاز دارد. حدود ریسک ورودهای معلق را لغو و در تصمیم بعدی خروج درخواست می‌کنند؛ شکاف و تعطیلی می‌تواند زیان را از حد عبور دهد.')}</p></details><p class="field-help">${text('Market fills, 500 ms latency, point-in-time rules. Starting cash is denominated in the selected markets’ common quote currency.', 'اجرای بازار، تأخیر ۵۰۰ میلی‌ثانیه و قواعد معتبر در همان زمان. موجودی اولیه برحسب ارز مظنهٔ مشترک بازارهای انتخابی است.')}</p><button id="portfolio-submit" class="button" type="submit">${text('Run shared-cash replay', 'اجرای بازپخش سبد')}</button></fieldset></form>
      <p id="portfolio-status" role="status" aria-live="polite"></p><div id="portfolio-saved"></div><div id="portfolio-result"></div><details class="disclosure"><summary>${text('Verify replay recovery', 'بررسی بازیابی بازپخش')}</summary><p class="field-help">${text('Rebuild an exact saved portfolio prefix, including pending orders, reservations and risk state. This is paper replay verification; it does not qualify physical-host or funded recovery.', 'پیشوند دقیق سبد ذخیره‌شده، شامل سفارش‌های معلق، مبالغ رزروشده و وضعیت ریسک بازسازی می‌شود. این بررسی بازپخش آزمایشی است و بازیابی روی میزبان دیگر یا با پول واقعی را تأیید نمی‌کند.')}</p>${field('portfolio-checkpoint-count', text('Observed quotes in prefix', 'تعداد قیمت‌های پیشوند'), 'type="number" min="1" max="100000" value="1"')}<div class="actions"><button id="portfolio-checkpoint" type="button" class="button">${text('Save recovery checkpoint', 'ثبت نقطه بازیابی')}</button><button id="portfolio-resume" type="button" class="button">${text('Rebuild and verify checkpoint', 'بازسازی و بررسی نقطه بازیابی')}</button></div><p id="portfolio-recovery-status" role="status"></p></details>`;
    const call = (action, value = null) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, ['portfolio-replay','replay-checkpoint','replay-resume'].includes(action) ? 135000 : 10000);
    const controls = () => {
      $('portfolio-load').disabled = busy; $('portfolio-fields').disabled = busy || !setup;
      $('portfolio-checkpoint').disabled = busy || !record; $('portfolio-resume').disabled = busy || !checkpoint;
    };
    async function act(work) {
      if (busy) return;
      busy = true; controls(); $('portfolio-status').textContent = text('Working…', 'در حال اجرا…');
      try { if (await work() !== false) $('portfolio-status').textContent = text('Request completed.', 'درخواست انجام شد.'); }
      catch { $('portfolio-status').textContent = text('Request failed. Check distinct observed markets, common quote, dates, cash and strategy parameters. Inspect saved portfolios before retrying; the calculation may have saved a result.', 'درخواست ناموفق بود. بازارهای متمایز، ارز مظنهٔ مشترک، تاریخ‌ها، موجودی و پارامترها را بررسی کنید. پیش از تکرار سبدهای ذخیره‌شده را بخوانید؛ ممکن است نتیجه ثبت شده باشد.'); }
      finally { busy = false; controls(); if (document.documentElement.lang !== language) mount({api, esc, table, keyValues, amount, when, curveFigure, strategyFields}); }
    }
    function fillSetup() {
      if (!setup) return;
      $('portfolio-markets').innerHTML = setup.symbols.map(s => `<option value="${esc(s)}"></option>`).join('');
      $('portfolio-resolution').innerHTML = setup.resolutions.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
      $('portfolio-strategy').innerHTML = setup.strategies.map(s => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join('');
      $('portfolio-resolution').value = setup.defaults.resolution;
      $('portfolio-fee').value = setup.defaults.fee_rate;
      renderParameters();
    }
    function renderParameters() {
      const entry = setup?.strategies.find(row => row.id === $('portfolio-strategy').value);
      if (!entry?.parameters || !strategyFields) return;
      try { $('portfolio-strategy-fields').innerHTML = strategyFields(entry, 'portfolio-parameter', JSON.parse($('portfolio-params').value || '{}')); }
      catch { $('portfolio-status').textContent = text('Correct the advanced parameter JSON before editing strategy controls.', 'پیش از ویرایش کنترل‌ها، JSON پارامترهای پیشرفته را اصلاح کنید.'); }
    }
    $('portfolio-strategy').onchange = () => { $('portfolio-params').value = '{}'; renderParameters(); };
    $('portfolio-params').onchange = renderParameters;
    $('portfolio-strategy-fields').oninput = event => {
      const key = event.target.dataset.parameter, entry = setup?.strategies.find(row => row.id === $('portfolio-strategy').value);
      const spec = entry?.parameters?.properties[key];
      if (!spec || busy) return;
      try {
        const params = JSON.parse($('portfolio-params').value || '{}');
        params[key] = spec.type === 'integer' ? Number(event.target.value) : event.target.value;
        $('portfolio-params').value = JSON.stringify(params);
      } catch { renderParameters(); }
    };
    async function savedRuns() {
      const data = await call('portfolio-list');
      $('portfolio-saved').innerHTML = `<p class="field-help">${text('Saved references; open a record to verify its contents and performance.', 'شناسه‌های ذخیره‌شده؛ برای بررسی محتوا و عملکرد، رکورد را باز کنید.')}</p>` + table([text('Saved portfolios · latest 100', 'سبدهای ذخیره‌شده · ۱۰۰ مورد آخر'), text('Strategy', 'راهبرد'), text('Markets', 'بازارها'), text('Window · Tehran', 'بازه · تهران')], data.runs.map(row => [
        `<button type="button" class="button button-small" data-portfolio="${esc(row.run_id)}">${esc(row.run_id)}</button>`, `${esc(row.inputs.strategy)} · ${esc(row.inputs.resolution)}`,
        `<details><summary>${esc(row.inputs.symbols.length)} · ${esc(row.inputs.symbols[0]?.endsWith('USDT') ? 'USDT' : 'TMN')}</summary><p dir="ltr">${esc(row.inputs.symbols.join(', '))}</p></details>`, `${esc(when(row.inputs.from))} → ${esc(when(row.inputs.to))}`]));
      $('portfolio-saved').querySelectorAll('[data-portfolio]').forEach(button => { button.onclick = () => act(async () => { record = await call('portfolio-read', {run_id: button.dataset.portfolio}); checkpoint = null; $('portfolio-recovery-status').textContent = ''; render(); }); });
    }
    function render() {
      if (!record) return;
      const result = record.result, end = result.end, valuation = result.valuation;
      const fxCurve = valuation?.curve || [];
      const conversion = valuation ? `<h4>${text('USDT equivalent · valuation only', 'معادل تتر · فقط ارزش‌گذاری')}</h4>` + keyValues([
        [text('Net · USDT equivalent', 'خالص · معادل تتر'), end.net_usdt_eq == null ? text('Unavailable', 'ناموجود') : amount(end.net_usdt_eq)],
        [text('Start / end FX status', 'وضعیت تبدیل ابتدا / انتها'), `${esc(valuation.start.status)} / ${esc(valuation.end.status)}`],
        [text('Valuation basis', 'مبنای ارزش‌گذاری'), esc(valuation.basis)]]) +
        (fxCurve.length && fxCurve.every(row => row.equity_usdt_eq != null) ? curveFigure({curve: fxCurve.map(row => [row.at, row.equity_usdt_eq]), quote: 'USDT equivalent'}) : '') +
        `<p class="field-help">${text('STALE and STALE_CLOSED use an old rate. UNAVAILABLE remains blank. Conversion does not make stale holdings current or certify an executable FX price.', 'STALE و STALE_CLOSED از نرخ قدیمی استفاده می‌کنند. UNAVAILABLE خالی می‌ماند. تبدیل، قیمت کهنهٔ دارایی را تازه نمی‌کند و قیمت قابل‌اجرا را تأیید نمی‌کند.')}</p>` +
        table([text('Latest 25 valuation marks · UTC', '۲۵ ارزش‌گذاری آخر · UTC'), text('USDT equivalent', 'معادل تتر'), text('FX status', 'وضعیت تبدیل'), text('Rate age · seconds', 'عمر نرخ · ثانیه')],
          fxCurve.slice(-25).map(row => [esc(when(row.at, false, 'UTC')), row.equity_usdt_eq == null ? text('Unavailable', 'ناموجود') : amount(row.equity_usdt_eq), esc(row.fx.status), esc(row.fx.age_seconds ?? 'UNKNOWN')])) : '';
      $('portfolio-result').innerHTML = `<h3>${esc(record.run_id)} · ${esc(result.quote)}</h3>` + (result.policy_state ? keyValues([
        [text('Portfolio risk latch', 'قفل ریسک سبد'), esc(result.policy_state.risk || 'CLEAR')],
        [text('Allocation readiness', 'آمادگی تخصیص'), esc(result.policy_state.weights.status)],
        [text('Policy scope', 'دامنه سیاست'), esc(result.policy_state.scope)]]) : '') + keyValues([
        [text('Equity · recorded bid marks', 'ارزش · قیمت خرید ثبت‌شده'), amount(end.equity)], [text('Net', 'خالص'), amount(end.net)],
        [text('Held-price freshness', 'تازگی قیمت دارایی‌ها'), esc(end.valuation_status || 'UNKNOWN')],
        [text('Remaining cash', 'نقد باقی‌مانده'), amount(result.balances?.[result.quote])],
        [text('Return · %', 'بازده · درصد'), amount(record.performance?.total_return_pct)],
        [text('Drawdown · sampled %', 'افت · درصد نمونه‌برداری‌شده'), amount(record.performance?.max_drawdown_pct)]]) + curveFigure(result) + table(
        [text('Market', 'بازار'), text('Fills', 'اجراها'), text('Closed trades', 'معاملات بسته'), text('Realized P/L', 'سود و زیان محقق'), text('Held · base units', 'دارایی · واحد پایه'), text('Last recorded bid', 'آخرین قیمت خرید ثبت‌شده'), text('Price freshness', 'تازگی قیمت'), text('Last mark · Tehran', 'آخرین قیمت · تهران')],
        Object.entries(result.markets).map(([s, row]) => [esc(s), esc(row.fills), esc(row.closed_trades), amount(row.realized_pnl), amount(row.holding), amount(row.last_bid), esc(row.mark_status || 'UNKNOWN'), esc(when(row.mark_time))])) +
        conversion + `<details><summary>${text('Verified inputs, orders and exact balances', 'ورودی، سفارش و موجودی دقیق بررسی‌شده')}</summary><pre class="output" dir="ltr">${esc(JSON.stringify(record, null, 2))}</pre></details>`;
    }
    $('portfolio-load').onclick = () => act(async () => {
      const data = await api('/api/research');
      if (!Array.isArray(data?.symbols) || !Array.isArray(data.resolutions) || !Array.isArray(data.strategies) || !data.defaults) throw new Error('Invalid research setup');
      if (data.portfolio_replay !== true) {
        setup = null;
        $('portfolio-status').textContent = text('The running observatory needs a restart to activate portfolio replay.', 'برای فعال‌شدن بازپخش سبد، رصدگر در حال اجرا باید دوباره راه‌اندازی شود.');
        return false;
      }
      setup = data; fillSetup(); await savedRuns();
    });
    for (const quote of ['USDT', 'TMN']) $('portfolio-all-' + quote.toLowerCase()).onclick = () => {
      if (busy || !setup) return;
      $('portfolio-symbols').value = setup.symbols.filter(symbol => symbol.endsWith(quote)).join(', ');
      $('portfolio-status').textContent = text(`All observed ${quote} markets selected. Enter starting cash in ${quote} units.`, `همهٔ بازارهای مشاهده‌شدهٔ ${quote} انتخاب شد. نقد اولیه را برحسب ${quote} وارد کنید.`);
    };
    $('portfolio-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      const policy = {method: $('portfolio-weighting').value || 'equal', lookback: Number($('portfolio-lookback').value || 20), max_weight: $('portfolio-cap').value || '1',
        cash_buffer: $('portfolio-buffer').value || '0', rebalance_seconds: Number($('portfolio-clock').value || 60), correlation_cap: $('portfolio-group-cap').value || '1',
        rebalance: $('portfolio-rebalance').value === 'true', rebalance_threshold: $('portfolio-threshold').value || '0.01'};
      for (const [id, key] of [['portfolio-drawdown', 'max_drawdown'], ['portfolio-daily-loss', 'daily_loss_limit']]) if ($(id).value) policy[key] = $(id).value;
      if ($('portfolio-correlation').value) policy.correlation_limit = $('portfolio-correlation').value;
      const result = await call('portfolio-replay', {symbols: $('portfolio-symbols').value.split(',').map(s => s.trim().toUpperCase()), policy,
        from: $('portfolio-from').value + 'Z', to: $('portfolio-to').value + 'Z', resolution: $('portfolio-resolution').value,
        cash: $('portfolio-cash').value, strategy: $('portfolio-strategy').value, params: JSON.parse($('portfolio-params').value),
        rules_mode: 'point-in-time', cost: {fee_rate: $('portfolio-fee').value, latency_ms: 500, max_wait_s: 60, fee_assumption: 'fee-in-received-asset'}});
      record = await call('portfolio-read', {run_id: result.run_id}); checkpoint = null; $('portfolio-recovery-status').textContent = ''; render(); await savedRuns();
    }); };
    fillSetup(); for (const [id, value] of Object.entries(saved)) $(id).value = value;
    $('portfolio-checkpoint').onclick = () => act(async () => {
      if (!record) throw new Error('Select a saved portfolio');
      checkpoint = (await call('replay-checkpoint', {run_id: record.run_id, quote_count: Number($('portfolio-checkpoint-count').value)})).record;
      $('portfolio-recovery-status').textContent = `${text('Saved checkpoint', 'نقطه بازیابی ثبت شد')}: ${checkpoint.run_id} · ${checkpoint.id}`;
    });
    $('portfolio-resume').onclick = () => act(async () => {
      if (!checkpoint) throw new Error('Save a checkpoint first');
      const result = await call('replay-resume', {checkpoint_id: checkpoint.id});
      $('portfolio-recovery-status').textContent = `${result.run_id} · ${result.status}`;
    });
    renderParameters();
    controls(); render();
  }
  return {mount};
})();
