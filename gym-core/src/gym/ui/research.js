/* Advanced research uses the same bounded service actions as gymctl research. */
window.gymResearch = (() => {
  let language;
  const actions = {
    register: ['Register hypothesis', 'ثبت فرضیه', 'symbol, strategy, params'],
    'shadow-open': ['Open paper shadow', 'بازکردن موقعیت سایه', 'position_id, hypothesis_id, quote, gross_quantity, fee_rate'],
    'shadow-close': ['Close paper shadow', 'بستن موقعیت سایه', 'position_id, quote'],
    schedule: ['Schedule hypothesis', 'زمان‌بندی فرضیه', 'hypothesis_id, every_seconds, lookback_seconds, first_at, resolution, cash, fee_rate'],
    list: ['Research ledger', 'دفتر پژوهش', ''],
    review: ['Review saved runs', 'بررسی اجراهای ذخیره‌شده', 'run_ids'],
    'claim-check': ['Check numeric claims', 'بررسی ادعاهای عددی', 'claims'],
    'outcome-add': ['Record run outcome', 'ثبت نتیجهٔ اجرا', 'Run ID'],
    outcomes: ['Available outcome memory', 'حافظهٔ نتایج قابل استفاده', ''],
    'final-register': ['Preregister future evaluation', 'پیش‌ثبت ارزیابی آینده', 'symbol, strategy, params, selection_end, test_from, test_to, resolution, cash, fee_rate'],
    'final-status': ['Inspect evaluation', 'بررسی ارزیابی', 'Evaluation ID'],
    'final-run': ['Consume evaluation once', 'اجرای یک‌بارهٔ ارزیابی', 'Evaluation ID'],
    'observe-import': ['Import observation vintages', 'ثبت نسخه‌های مشاهدات', 'observations'],
    screen: ['Screen supplied observations', 'غربال مشاهدات ورودی', 'source_id, series, kind, unit, as_of, descending, limit, max_age_seconds'],
    diagnostic: ['Evaluate accounting or market model', 'ارزیابی مدل بازار یا حسابداری', 'model, parameters'],
    technicals: ['Closed-bar technical timeframes', 'تحلیل بازه‌های شمع بسته', 'symbol, from, to, resolutions'],
    spreads: ['Observed spread report', 'گزارش فاصلهٔ قیمت مشاهده‌شده', 'symbol, from, to'],
    'trade-flow': ['Recorded trade flow', 'جریان معاملات ثبت‌شده', 'symbol, from, to'],
  };
  const idActions = new Set(['outcome-add', 'final-status', 'final-run']);
  const $ = id => document.getElementById(id);
  function mount(api, esc) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next) return;
    language = next;
    const fa = language === 'fa';
    $('research-workbench').innerHTML = `<h2>${fa ? 'کارگاه پیشرفتهٔ پژوهش' : 'Advanced research workbench'}</h2><p class="field-help">${fa ? 'ورودی‌های محلی و نتایج آزمایشی؛ هیچ سفارشی ارسال نمی‌شود. ارزیابی آینده فقط یک‌بار مصرف می‌شود، حتی اگر اجرا شکست بخورد.' : 'Local inputs and paper results. No orders are sent. A future evaluation is consumed once, including when execution fails.'}</p><form id="research-action-form"><label for="research-action">${fa ? 'عملیات' : 'Workflow'}</label><select id="research-action">${Object.entries(actions).map(([id, labels]) => `<option value="${id}">${esc(labels[fa ? 1 : 0])}</option>`).join('')}</select><label for="research-action-input">${fa ? 'ورودی JSON یا شناسه' : 'Input JSON or saved ID'}</label><textarea id="research-action-input" rows="5" dir="ltr" spellcheck="false" aria-describedby="research-action-fields"></textarea><p id="research-action-fields" class="field-help" dir="ltr"></p><button class="button" type="submit">${fa ? 'اجرای عملیات' : 'Run workflow'}</button></form><p id="research-action-status" role="status"></p><pre id="research-action-result" class="output" dir="ltr"></pre>`;
    function update() {
      const action = $('research-action').value;
      $('research-action-fields').textContent = actions[action][2];
      $('research-action-input').disabled = !actions[action][2];
      $('research-action-input').required = !!actions[action][2];
    }
    $('research-action').onchange = update; update();
    $('research-action-form').onsubmit = async event => {
      event.preventDefault();
      const submit = event.target.querySelector('button'); submit.disabled = true;
      $('research-action-status').textContent = '';
      try {
        const action = $('research-action').value;
        const input = $('research-action-input').value;
        const value = !actions[action][2] ? null : idActions.has(action) ? input.trim() : JSON.parse(input);
        const result = await api('/api/research/action', { method: 'POST', body: JSON.stringify({ action, value }) }, 120000);
        $('research-action-result').textContent = JSON.stringify(result, null, 2);
      } catch { $('research-action-status').textContent = fa ? 'عملیات ناموفق بود. ورودی و وضعیت دفتر را بررسی کنید؛ ارزیابی نهایی را تکرار نکنید.' : 'Workflow failed. Check the input and ledger state. Do not repeat a consumed final evaluation.'; }
      finally { submit.disabled = false; }
    };
  }
  return { mount };
})();
