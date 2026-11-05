/* Public Wallex terms and local paper replay share the CLI research actions. */
window.gymMargin = (() => {
  let language, catalogue, preview, busy = false;
  const $ = id => document.getElementById(id);
  const inputIds = ['margin-market', 'margin-side', 'margin-collateral', 'margin-risk', 'margin-price', 'margin-stop', 'margin-target', 'margin-from', 'margin-to', 'margin-exit-fee', 'margin-holding'];
  function mount({api, esc, keyValues, table, amount, when, demo = false}) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next || busy) return;
    // A language change preserves the operator's exact decimal inputs and receipt.
    const saved = language ? Object.fromEntries(inputIds.map(id => [id, $(id).value])) : {};
    language = next;
    const fa = language === 'fa', text = (en, persian) => fa ? persian : en;
    const field = (id, title, attributes = '') => `<label for="${id}">${title}</label><input id="${id}" dir="ltr" ${attributes}>`;
    $('margin-workbench').innerHTML = `<h2>${text('Wallex margin · LONG / SHORT paper positions', 'معاملهٔ تعهدی والکس · موقعیت آزمایشی لانگ / شورت')}</h2>
      <p class="field-help">${text('Load current market credit limits, obtain the public loan calculator and preview, then replay recorded quotes. No real loan or position is opened. Credit ratio is Wallex risk_coef; do not treat it as a futures leverage switch.', 'محدودیت اعتبار بازار را دریافت کنید، محاسبهٔ وام و پیش‌نمایش عمومی بگیرید و مشاهدات ثبت‌شده را بازپخش کنید. وام یا موقعیت واقعی باز نمی‌شود. نسبت اعتبار همان risk_coef والکس است.')}</p>
      <button id="margin-load" type="button" class="button">${text('Load current margin rules', 'دریافت قواعد فعلی تعهدی')}</button><div id="margin-rules"></div>
      <form id="margin-preview-form"><fieldset id="margin-preview-fields" disabled><legend>${text('Venue preview · no order', 'پیش‌نمایش صرافی · بدون سفارش')}</legend><div class="ticket-fields">
      <label for="margin-market">${text('Margin market', 'بازار تعهدی')}</label><select id="margin-market" dir="ltr"></select>
      <label for="margin-side">${text('Direction', 'جهت')}</label><select id="margin-side" dir="ltr"><option value="long">LONG</option><option value="short">SHORT</option></select>
      ${field('margin-collateral', text('Collateral · quote currency', 'وثیقه · ارز مظنه'), 'required type="text" inputmode="decimal"')}
      ${field('margin-risk', text('Credit ratio · venue grid', 'نسبت اعتبار · گام صرافی'), 'required type="number"')}
      ${field('margin-price', text('Entry limit price', 'قیمت محدود ورود'), 'required type="text" inputmode="decimal"')}
      ${field('margin-stop', text('Stop loss · optional', 'حد ضرر · اختیاری'), 'type="text" inputmode="decimal"')}
      ${field('margin-target', text('Take profit · optional', 'حد سود · اختیاری'), 'type="text" inputmode="decimal"')}
      </div><button id="margin-observed-price" type="button" class="button">${text('Use observed bid / ask', 'استفاده از قیمت خرید / فروش مشاهده‌شده')}</button>
      <button type="submit" class="button">${text('Check collateral and preview', 'بررسی وثیقه و پیش‌نمایش')}</button></fieldset></form><div id="margin-preview"></div>
      <form id="margin-replay-form"><fieldset id="margin-replay-fields" disabled><legend>${text('Replay observed quotes · paper only', 'بازپخش مشاهدات · فقط آزمایشی')}</legend><div class="ticket-fields">
      ${field('margin-from', text('From · UTC · after preview receipt', 'از · UTC · پس از دریافت پیش‌نمایش'), 'required type="datetime-local" step="1"')}
      ${field('margin-to', text('To · UTC · exclusive', 'تا · UTC · انتهای باز'), 'required type="datetime-local" step="1"')}
      ${field('margin-exit-fee', text('Assumed exit fee · quote currency · decimal fraction', 'کارمزد فرضی خروج · ارز مظنه · کسر اعشاری'), 'required type="text" inputmode="decimal"')}
      ${field('margin-holding', text('Close after seconds · optional', 'بستن پس از چند ثانیه · اختیاری'), 'type="number" min="1" step="1"')}
      </div><button id="margin-cutoff" type="button" class="button">${text('Use current cutoff', 'استفاده از زمان فعلی برای انتها')}</button><button type="submit" class="button">${text('Replay paper position', 'بازپخش موقعیت آزمایشی')}</button></fieldset></form>
      <p id="margin-status" role="status"></p><div id="margin-result" aria-live="polite"></div>`;
    const call = (action, value) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, 130000);
    function receipt(value, kind) {
      if (value?.schema !== 'wallex-margin/1' || value.kind !== kind || !/^[0-9a-f]{16}$/.test(value.run_id || '') || value.funded_authority !== false || value.order_submitted !== false) throw new Error('invalid paper receipt');
      if (kind === 'MARKETS' && !Array.isArray(value.markets)) throw new Error('missing rules');
      if (kind === 'PREVIEW' && (!value.collateral_limits || !value.terms || !['collateral', 'loan', 'trade_fee', 'open_fee', 'extend_fee'].every(key => value.terms[key]?.currency && typeof value.terms[key]?.value === 'string'))) throw new Error('missing terms');
      return value;
    }
    const money = row => `${amount(row.value)} <bdi dir="ltr">${esc(row.currency)}</bdi>`;
    const raw = value => `<details><summary>${text('Saved receipt and limitations', 'رسید ذخیره‌شده و محدودیت‌ها')}</summary><pre class="output" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre></details>`;
    function controls() {
      $('margin-load').disabled = busy || demo;
      $('margin-preview-fields').disabled = busy || !catalogue;
      $('margin-replay-fields').disabled = busy || !preview;
    }
    async function act(fn) {
      if (busy || demo) return;
      busy = true; controls(); $('margin-status').textContent = '';
      try { await fn(); }
      catch { $('margin-status').textContent = text('Request failed. Refresh market rules and check collateral, credit step, protection prices and quote coverage. Saved terms require a window after their receipt. No order was submitted.', 'درخواست ناموفق بود. قواعد بازار، وثیقه، گام اعتبار، قیمت‌های حفاظتی و پوشش داده را بررسی کنید. بازه باید پس از دریافت پیش‌نمایش باشد. سفارشی ارسال نشد.'); }
      finally { busy = false; controls(); if (document.documentElement.lang !== language) mount({api, esc, keyValues, table, amount, when, demo}); }
    }
    function renderRules() {
      if (!catalogue) return;
      $('margin-market').innerHTML = catalogue.markets.map(row => `<option>${esc(row.symbol)}</option>`).join('');
      $('margin-rules').innerHTML = `<p>${text('Received', 'دریافت')} · ${esc(when(catalogue.received_at))}</p><details><summary>${text('Per-market rules', 'قواعد هر بازار')} · ${catalogue.markets.length}</summary>` + table(
        [text('Market', 'بازار'), text('Minimum credit', 'کمینه اعتبار'), text('Maximum credit', 'بیشینه اعتبار'), text('Step', 'گام'), text('Liquidation margin · fraction', 'حاشیه لیکوییدی · کسر'), text('Max age · seconds', 'بیشینه عمر · ثانیه')],
        catalogue.markets.map(row => [esc(row.symbol), amount(row.min_risk_coef), amount(row.max_risk_coef), amount(row.risk_coef_step), amount(row.liquidity_margin), esc(row.max_age)])) + '</details>';
    }
    function bounds() {
      const row = catalogue?.markets.find(row => row.symbol === $('margin-market').value);
      if (!row) return;
      for (const [name, value] of [['min', row.min_risk_coef], ['max', row.max_risk_coef], ['step', row.risk_coef_step]]) $('margin-risk').setAttribute(name, value);
      if (!$('margin-risk').value) $('margin-risk').value = row.min_risk_coef;
      $('margin-holding').max = row.max_age;
    }
    function renderPreview() {
      if (!preview) return;
      const terms = preview.terms;
      $('margin-preview').innerHTML = keyValues([
        [text('Saved preview', 'پیش‌نمایش ذخیره‌شده'), esc(preview.run_id)],
        [text('Collateral range', 'بازه وثیقه'), `${amount(preview.collateral_limits.min)} – ${amount(preview.collateral_limits.max)} ${esc(terms.collateral.currency)}`],
        [text('Loan', 'وام'), money(terms.loan)], [text('Opening fee', 'کارمزد باز کردن'), money(terms.open_fee)],
        [text('Entry trading fee', 'کارمزد معامله ورود'), money(terms.trade_fee)], [text('Extension fee', 'کارمزد تمدید'), money(terms.extend_fee)],
        [text('Extension period · seconds', 'دوره تمدید · ثانیه'), esc(terms.extend_time)],
        [text('Warning price', 'قیمت هشدار'), amount(terms.call_price)], [text('Liquidation price', 'قیمت لیکوییدی'), amount(terms.liquidity_price)],
        [text('Max age · seconds', 'بیشینه عمر · ثانیه'), esc(terms.max_age)],
      ]) + raw(preview);
    }
    function invalidate() { preview = null; $('margin-preview').textContent = ''; $('margin-result').textContent = ''; controls(); }
    $('margin-load').onclick = () => act(async () => { invalidate(); catalogue = null; $('margin-rules').textContent = ''; catalogue = receipt(await call('margin-markets', null), 'MARKETS'); renderRules(); bounds(); });
    $('margin-market').onchange = () => { invalidate(); $('margin-risk').value = ''; bounds(); };
    $('margin-preview-form').oninput = invalidate;
    $('margin-observed-price').onclick = () => act(async () => {
      const data = await api('/api/markets');
      const row = data.markets.find(row => row.symbol === $('margin-market').value);
      if (!row?.qualified || row.book_age_s == null || row.book_age_s < 0 || row.book_age_s > 30) throw new Error('quote unavailable');
      invalidate(); $('margin-price').value = row[$('margin-side').value === 'long' ? 'ask' : 'bid'];
    });
    $('margin-preview-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      invalidate();
      const request = {market: $('margin-market').value, side: $('margin-side').value, collateral: $('margin-collateral').value, risk_coef: $('margin-risk').value, open_price: $('margin-price').value};
      for (const [id, key] of [['margin-stop', 'stop_loss'], ['margin-target', 'take_profit']]) if ($(id).value) request[key] = $(id).value;
      const response = await call('margin-preview', {catalogue_id: catalogue.run_id, request});
      if (response.kind === 'COLLATERAL_LIMITS') {
        const limits = receipt(response, 'COLLATERAL_LIMITS').collateral_limits;
        $('margin-preview').innerHTML = keyValues([[text('Required collateral range', 'بازه مجاز وثیقه'), `${amount(limits.min)} – ${amount(limits.max)} ${esc(limits.currency)}`]]);
        return;
      }
      preview = receipt(response, 'PREVIEW'); renderPreview();
      $('margin-from').value = new Date(Date.parse(preview.received_at) + 1000).toISOString().slice(0, 19);
      $('margin-holding').max = preview.terms.max_age;
    }); };
    $('margin-cutoff').onclick = () => { $('margin-to').value = new Date().toISOString().slice(0, 19); };
    $('margin-replay-form').onsubmit = event => { event.preventDefault(); return act(async () => {
      const result = await call('margin-replay', {preview_id: preview.run_id, from: $('margin-from').value + 'Z', to: $('margin-to').value + 'Z', exit_fee_rate: $('margin-exit-fee').value, holding_seconds: $('margin-holding').value ? Number($('margin-holding').value) : null});
      const row = result.result;
      $('margin-result').innerHTML = keyValues([
        [text('Paper state', 'وضعیت آزمایشی'), esc(row.state)], [text('Cash · quote', 'نقد · ارز مظنه'), amount(row.cash_quote)],
        [text('Base holdings', 'دارایی پایه'), amount(row.base_units)], [text('Quote debt', 'بدهی مظنه'), amount(row.debt_quote)],
        [text('Base debt', 'بدهی پایه'), amount(row.debt_base)], [text('Marked equity · quote', 'ارزش خالص · مظنه'), amount(row.equity_quote)],
        [text('Quote status', 'وضعیت مظنه'), esc(row.mark.status)],
      ]) + table([text('Fee currency', 'ارز کارمزد'), text('Recognized costs', 'هزینه ثبت‌شده')], Object.entries(row.fees_by_currency || {}).map(([currency, value]) => [esc(currency), amount(value)]))
        + table([text('Time · UTC', 'زمان · UTC'), text('Paper event', 'رویداد آزمایشی'), text('Observed side price', 'قیمت سمت مشاهده‌شده')], row.events.map(row => [esc(row.at), esc(row.action), amount(row.price)])) + raw(result);
    }); };
    renderRules();
    for (const [id, value] of Object.entries(saved)) $(id).value = value;
    bounds(); renderPreview(); controls();
  }
  return {mount};
})();
