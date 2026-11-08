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
    derived: ['Aligned ratios and spreads', 'نسبت‌ها و اختلاف‌های هم‌زمان', 'left, right, operation, as_of, max_age_seconds, max_skew_seconds'],
    diagnostic: ['Evaluate accounting or market model', 'ارزیابی مدل بازار یا حسابداری', 'model, parameters'],
    technicals: ['Closed-bar technical timeframes', 'تحلیل بازه‌های شمع بسته', 'symbol, from, to, resolutions'],
    spreads: ['Observed spread report', 'گزارش فاصلهٔ قیمت مشاهده‌شده', 'symbol, from, to'],
    'trade-flow': ['Recorded trade flow', 'جریان معاملات ثبت‌شده', 'symbol, from, to'],
    candles: ['Point-in-time candle crosscheck', 'تطبیق شمع با زمان آگاهی', 'symbol, from, to, as_of, tolerance_bps'],
    'market-screen': ['Rank recorded markets', 'رتبه‌بندی بازارهای ثبت‌شده', 'symbols, reference, quote_currency, from, to, resolution, metric'],
    rebalance: ['Preview target rebalance', 'پیش‌نمایش توازن سبد', 'quote_currency, cash, reserved_cash, fee_rate, positions: [{symbol, held, reserved, target_weight, bid, ask, quantity_step, minimum_quote}]'],
    'execution-quality': ['Compare supplied fills', 'مقایسه اجرای ورودی', 'run_id, observations: [{fill_id, order_ref, side, quantity, price, fee, fee_currency, filled_at, observed_at}]'],
    'experiment-run': ['Run experiment and stress scenarios', 'اجرای آزمایش و سناریوهای تنش', 'hypothesis, symbol, strategy, trials: [params], windows: [{from, to}], resolution, cash, scenarios: [{fee_rate, latency_ms, outages: [{from, to}]}], final_evaluation_id (null or saved ID)'],
    'experiment-list': ['Experiment registry', 'دفتر آزمایش‌ها', ''],
    'experiment-status': ['Inspect saved experiment or note', 'بررسی آزمایش یا یادداشت', 'Saved registry ID'],
    'research-packet': ['Prepare AI evidence packet', 'آماده‌سازی شواهد برای هوش مصنوعی', 'run_ids'],
    'research-notes': ['Validate and save analyst notes', 'بررسی و ذخیره یادداشت تحلیلگر', 'packet_id, preset, notes: [{role, observation, citations, claims, disagrees_with}]'],
  };
  const idActions = new Set(['outcome-add', 'final-status', 'final-run', 'experiment-status', 'prospective-status', 'prospective-evaluate']);
  actions['premium-research'] = ['Analyze TMN conversion premium', 'بررسی صرف تبدیل تومان', 'base, from, to, resolution, max_age_seconds, max_skew_seconds, fee_rate; descriptive, no executable arbitrage'];
  actions['lead-lag-research'] = ['Test causal lead-lag alignment', 'بررسی تقدم و تأخر علّی', 'primary, leader, from, to, resolution, max_age_seconds, max_skew_seconds, min_overlap; optional max_delay_bars (1..12), strictly earlier training-only lag choice; descriptive only'];
  actions['twap-preview'] = ['Preview paper TWAP child fills', 'پیش‌نمایش برش‌های آزمایشی TWAP', 'symbol, from, to, side (BUY/SELL), quantity, slices, participation, fee_rate, available_quote, available_base, max_delay_seconds; optional cost_models (dated impact_models/hourly_costs); paper-only'];
  actions['prospective-register'] = ['Freeze future strategy comparison', 'ثبت ثابت مقایسهٔ آینده', 'symbol, candidates: [{strategy, params}], selection_end, test_from, test_to, resolution, cash, fee_rate; window must be in future'];
  actions['prospective-status'] = ['Inspect frozen comparison', 'بررسی مقایسهٔ ثبت‌شده', 'Saved 64-character registry ID'];
  actions['prospective-evaluate'] = ['Consume future comparison once', 'اجرای یک‌بارهٔ مقایسهٔ آینده', 'Saved 64-character registry ID; failures are consumed'];
  actions['market-products'] = ['Inspect observed market products and credit grids', 'بررسی محصولات بازار و گام اعتبار', 'margin_catalogue_id: null or saved public MARKETS receipt ID; stale terms cannot establish current availability'];
  actions['campaign-status'] = ['Inspect campaign progress and verified samples', 'پیشرفت مطالعه و نمونه‌های بررسی‌شده', 'limit: 1..100; complete journal counts, bounded verified readiness/trade sample; process liveness remains separate'];
  actions['walk-forward'] = ['Expanding walk-forward search', 'جست‌وجوی پیش‌رونده با آموزش افزایشی', 'hypothesis, symbol, candidates: [{strategy, params}], windows: [{train_from, train_to, test_from, test_to}], final_from, resolution, cash, fee_rate, latency_ms, purge_bars'];
  actions['execution-calibration'] = ['Inspect execution assumption evidence', 'بررسی شواهد فرض‌های اجرا', 'symbol (null for all markets), from, to, max_age_seconds; public feed timing only, no automatic cost defaults'];
  actions['execution-model-calibrate'] = ['Fit causal public impact and hourly cost models', 'برازش علّی اثر قیمت و هزینهٔ ساعتی', 'symbol, from, to; bounded historical public prints, quotes, and local read-only fee receipts; paper-only, opt in explicitly'];
  actions['robustness'] = ['Inspect selection and path robustness', 'بررسی پایداری انتخاب و مسیر', 'run_ids, partitions (4/6/8/10), seed, simulations, mean_block_length, max_gap_seconds; comparable verified historical runs only'];
  actions['strategy-audit'] = ['Check causality and warm-up', 'بررسی علیت و دورهٔ آماده‌سازی', 'symbol, strategy, params, from, to, resolution, cash, fee_rate, latency_ms, checkpoints: [time], history_starts: [time]'];
  actions['return-bootstrap'] = ['Explore saved return uncertainty', 'بررسی عدم‌قطعیت بازده ثبت‌شده', 'run_id, seed, simulations, mean_block_length, max_gap_seconds'];
  actions['fractional-sizing'] = ['Analyze capped fractional Kelly sizing', 'تحلیل اندازه‌گذاری محدود کلی', 'evaluation_id (completed preregistered evaluation), fraction (0..0.5 multiplier), cap (0..0.25), seed, simulations (100..500), block_length (1..50); no allocation changes automatically'];
  actions['experiment-scorecard'] = ['Experiment scorecard and parameter heatmap', 'کارنامهٔ آزمایش و نقشهٔ پارامترها', 'experiment_id, shadow_run_ids: up to four matched native prospective session IDs, or []'];
  actions['job-interrupt'] = ['Release an interrupted paper attempt', 'آزادسازی تلاش متوقف‌شدهٔ آزمایشی', 'job_id, expected_due, expected_claim, reason (fences publication; does not terminate a process)'];
  actions['return-correlations'] = ['Compare aligned market returns', 'مقایسهٔ بازده هم‌زمان بازارها', 'symbols: [market], quote_currency, from, to, resolution, min_overlap'];
  actions['registry-page'] = ['Browse a registry snapshot', 'مرور نسخهٔ ثابت دفتر پژوهش', 'kind (null or event kind), parent (null or saved ID), after, through (null for first page), limit'];
  actions['annotation-add'] = ['Save replay annotation', 'ثبت یادداشت مرور', 'run_id, outputs_digest, decision_index, request_id (32 hex characters), text'];
  actions['annotation-list'] = ['Read replay annotations', 'خواندن یادداشت‌های مرور', 'run_id, outputs_digest, after, through, limit'];
  actions['replay-checkpoint'] = ['Save verified replay checkpoint', 'ثبت نقطهٔ بازیابی مرور', 'run_id, quote_count'];
  actions['replay-resume'] = ['Resume and verify saved replay', 'ادامه و بررسی مرور ثبت‌شده', 'checkpoint_id'];
  actions['entry-lock-add'] = ['Record paper entry lock', 'ثبت محدودیت ورود آزمایشی', 'run_id, scope (PAIR/GLOBAL), reason (COOLDOWN/DRAWDOWN), duration_seconds, threshold_percent (null for cooldown)'];
  actions['entry-locks'] = ['Inspect paper entry locks', 'بررسی محدودیت‌های ورود آزمایشی', ''];
  actions['conversion-report'] = ['Evaluate modeled conversion', 'ارزیابی تبدیل شبیه‌سازی‌شده', 'instruction, fills, mark_price, observed_at (offline modeled fills only)'];
  actions['probe-stage'] = ['Stage offline probe budget', 'ثبت بودجهٔ بررسی آفلاین', 'total_loss_limit, quote_asset, probe: {probe_id, kind, symbol, worst_case_total_loss, venue_minimum_quote} (no permission to trade)'];
  actions['external-import'] = ['Import manual account observations', 'ثبت مشاهدات دستی حساب', 'account_id, observed_at, balances, orders, exposure (sanitized observations only; no credentials)'];
  actions['venue-fact-import'] = ['Import sanitized venue evidence', 'ثبت شواهد پالایش‌شدهٔ بازار', 'evidence_id, observed_at, source, kind, endpoint, state, account_scope, response_version, evidence_sha256'];
  actions['evidence-report'] = ['Inspect saved economic evidence', 'بررسی شواهد اقتصادی ثبت‌شده', 'run_id'];
  actions['evidence-decision'] = ['Record offline evidence decision', 'ثبت تصمیم آفلاین دربارهٔ شواهد', 'run_id, claim (NONE/EXPERIMENTAL), cap (decimal string), currency (USDT/TMN), note; record only'];
  actions['depth-audit'] = ['Validate supplied depth sequence', 'بررسی توالی عمق ورودی', 'source_id, as_of, max_age_seconds, max_levels, frames: [{kind, sequence, previous_sequence, event_at, observed_at, bids: [[price, quantity]], asks: [[price, quantity]]}]'];
  actions['unit-convert'] = ['Convert explicit observation epochs', 'تبدیل دوره‌های واحد مشاهده', 'value, factor (exact observation references), from_epoch, to_epoch, target_unit, as_of, max_age_seconds, max_skew_seconds'];
  actions['market-breadth'] = ['Compare market group breadth', 'مقایسهٔ گسترهٔ گروه‌های بازار', 'groups: [{name, symbols}], quote_currency, from, to, resolution'];
  actions['order-page-import'] = ['Import observed order page', 'ثبت صفحهٔ سفارش‌های مشاهده‌شده', 'account_id, observed_at, kind (OPEN/HISTORY), page, per_page, payload (documented map of order arrays; origin and completeness remain unverified)'];
  actions['news-fetch'] = ['Fetch public Federal Reserve headlines', 'دریافت خبرهای عمومی فدرال رزرو', 'source: "FED_PRESS", max_items: 1..20 (explicit internet read; saves actual receipt times, no historical backfill or trading signal)'];
  const $ = id => document.getElementById(id);
  function mount(api, esc) {
    const next = document.documentElement.lang === 'fa' ? 'fa' : 'en';
    if (language === next) return;
    language = next;
    const fa = language === 'fa';
    workspace(api, esc, fa);
    $('research-workbench').innerHTML = `<h2>${fa ? 'کارگاه پیشرفتهٔ پژوهش' : 'Advanced research workbench'}</h2><p class="field-help">${fa ? 'ورودی‌های محلی و نتایج آزمایشی؛ هیچ سفارشی ارسال نمی‌شود. ارزیابی آینده فقط یک‌بار مصرف می‌شود، حتی اگر اجرا شکست بخورد.' : 'Local inputs and paper results. No orders are sent. A future evaluation is consumed once, including when execution fails.'}</p><form id="research-action-form"><label for="research-action">${fa ? 'عملیات' : 'Workflow'}</label><select id="research-action">${Object.entries(actions).map(([id, labels]) => `<option value="${id}">${esc(labels[fa ? 1 : 0])}</option>`).join('')}</select><label for="research-action-input">${fa ? 'ورودی JSON یا شناسه' : 'Input JSON or saved ID'}</label><textarea id="research-action-input" rows="5" dir="ltr" spellcheck="false" aria-describedby="research-action-fields"></textarea><p id="research-action-fields" class="field-help" dir="ltr"></p><button class="button" type="submit">${fa ? 'اجرای عملیات' : 'Run workflow'}</button></form><p id="research-action-status" role="status"></p><pre id="research-action-result" class="output" dir="ltr"></pre>`;
    $('research-action-input').className = 'input code';
    const groups = [
      ['Schedules and recovery', 'زمان‌بندی و بازیابی', /^(schedule|job-|campaign-status$|list$)/],
      ['Experiments and replay', 'آزمایش‌ها و بازپخش', /^(register$|review$|experiment-|registry-|annotation-|replay)/],
      ['Markets and observations', 'بازارها و مشاهدات', /^(premium-|lead-lag-|technical|spreads$|trade-flow$|candles$|market-|depth-|unit-|derived$|screen$|observe-|news-)/],
      ['Research evidence and evaluation', 'شواهد پژوهش و ارزیابی', /^(research-|prospective-|claim-check$|outcome|final-)/],
      ['Account and execution diagnostics', 'حساب و تشخیص اجرا', /./],
    ];
    $('research-action').innerHTML = groups.map(([en, persian], index) => `<optgroup label="${esc(fa ? persian : en)}">${Object.entries(actions)
      .filter(([id]) => groups.findIndex(group => group[2].test(id)) === index)
      .map(([id, labels]) => `<option value="${id}">${esc(labels[fa ? 1 : 0])}</option>`).join('')}</optgroup>`).join('');
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
      $('research-action-status').textContent = fa ? 'در حال اجرا…' : 'Working…';
      $('research-action-result').textContent = '';
      try {
        const action = $('research-action').value;
        const input = $('research-action-input').value;
        const value = !actions[action][2] ? null : idActions.has(action) ? input.trim() : JSON.parse(input);
        const result = await api('/api/research/action', { method: 'POST', body: JSON.stringify({ action, value }) }, 130000);
        $('research-action-result').textContent = JSON.stringify(result, null, 2);
        document.getElementById('experiment-scorecard')?.remove();
        if (action === 'experiment-scorecard') scorecard(result, esc, fa);
        $('research-action-status').textContent = fa ? 'درخواست انجام شد.' : 'Request completed.';
        if (action === 'research-packet') {
          $('research-packet-prompt').value = result.prompt;
          $('research-packet-id').textContent = result.packet.id;
          $('research-packet-send').disabled = false;
        }
      } catch { $('research-action-status').textContent = fa ? 'نتیجه دریافت نشد. ممکن است عملیات ثبت شده باشد؛ پیش از تکرار، ورودی و وضعیت ذخیره‌شده را بررسی کنید. ارزیابی مصرف‌شده را تکرار نکنید.' : 'Result was not delivered. The operation may have committed; inspect the input and saved state before retrying. Do not repeat a consumed evaluation.'; }
      finally { submit.disabled = false; }
    };
  }
  function scorecard(report, esc, fa) {
    const text = (en, persian) => fa ? persian : en;
    const host = document.createElement('section'); host.id = 'experiment-scorecard'; host.className = 'panel';
    const definitions = report.definition;
    host.innerHTML = `<h3>${text('Every registered trial', 'تمام تلاش‌های ثبت‌شده')}</h3><p>${esc(report.registered_trials)} ${text('parameter trials', 'ترکیب پارامتر')} · ${esc(report.registered_attempts)} ${text('attempts including failures', 'تلاش با احتساب شکست‌ها')}</p>
      <div class="table-wrap" tabindex="0"><table class="data"><caption>${text('Net result in quote currency · unready or stale cells stay neutral', 'نتیجهٔ خالص در ارز مظنه · سلول‌های ناآماده یا قدیمی خنثی می‌مانند')}</caption><thead><tr><th>${text('Window / cost', 'دوره / هزینه')}</th>${definitions.trials.map((params, i) => `<th scope="col">${i + 1}<br><code>${esc(JSON.stringify(params))}</code></th>`).join('')}</tr></thead><tbody>${definitions.windows.flatMap((period, w) => definitions.scenarios.map((cost, s) => `<tr><th scope="row"><time dir="ltr">${esc(period.from)} → ${esc(period.to)}</time><br><code>${esc(JSON.stringify(cost))}</code></th>${definitions.trials.map((_, trial) => {
        const row = report.rows.find(r => r.trial === trial && r.window === w && r.scenario === s), run = row?.run;
        const valid = run?.ready && run.valuation.status === 'CURRENT' && run.net_quote != null;
        const tone = valid && Number(run.net_quote) !== 0 ? Number(run.net_quote) > 0 ? 'positive' : 'negative' : 'neutral';
        const capacity = row?.capacity ?? run?.capacity;
        const capacityLabel = capacity?.capacity_usdt != null
          ? `${text('Modeled capacity', 'ظرفیت برآوردی')}: ${capacity.capacity_usdt} USDT`
          : `${text('Capacity unavailable', 'ظرفیت ناموجود')}: ${capacity?.reason ?? 'NO_VERIFIED_RUN'}`;
        return `<td class="heat-${tone}">${esc(run?.net_quote ?? row?.verification ?? row?.state ?? 'RESULT_PENDING')} ${esc(run?.quote ?? '')}<br>${esc(row?.verification ?? row?.state ?? '')}<br>${esc(run ? `${run.ready ? 'READY' : 'NOT_READY'} · ${run.valuation.status} · ${run.fills} fills` : row?.reason ?? '')}<br><small>${esc(capacityLabel)}</small></td>`;
      }).join('')}</tr>`)).join('')}</tbody></table></div><p class="field-help">${report.limits.map(esc).join(' ')}</p>
      <form id="scorecard-overlay-form"><fieldset><legend>${text('Choose two to four recorded paths to overlay', 'دو تا چهار مسیر ثبت‌شده را برای مقایسه انتخاب کنید')}</legend></fieldset><button class="button" type="submit">${text('Compare selected paths', 'مقایسهٔ مسیرهای انتخاب‌شده')}</button></form><p id="scorecard-overlay-status" role="status"></p><div id="scorecard-overlay"></div>`;
    $('research-action-result').before(host);
    const runs = [...new Map([...report.rows.filter(r => r.run).map(r => r.run), ...report.shadows].map(run => [run.run_id, run])).values()];
    host.querySelector('fieldset').insertAdjacentHTML('beforeend', runs.map(run => `<label class="check"><input type="checkbox" name="path" value="${esc(run.run_id)}">${esc(`${run.kind} · ${run.run_id} · ${run.valuation.status}`)}</label>`).join(''));
    $('scorecard-overlay-form').onsubmit = event => {
      event.preventDefault();
      const ids = [...host.querySelectorAll('input[name="path"]:checked')].map(input => input.value);
      if (ids.length < 2 || ids.length > 4) { $('scorecard-overlay-status').textContent = text('Choose two to four paths.', 'دو تا چهار مسیر انتخاب کنید.'); return; }
      $('scorecard-overlay-status').textContent = text('Recorded times; each path starts at its own initial cash. No calendar alignment or interpolation.', 'زمان‌های ثبت‌شده؛ هر مسیر از وجه نقد آغازین خود شروع می‌شود. هم‌ترازی تقویمی یا درون‌یابی انجام نمی‌شود.');
      $('scorecard-overlay').innerHTML = overlayFigure(runs.filter(run => ids.includes(run.run_id)).map(run => ({name:`${run.kind} · ${run.run_id}`, curve:run.curve})));
    };
  }
  function workspace(api, esc, fa) {
    let host = $('research-workspace');
    if (!host) {
      host = document.createElement('section'); host.id = 'research-workspace'; host.className = 'panel';
      $('research-workbench').before(host);
    }
    const text = (en, persian) => fa ? persian : en;
    const resolutions = JSON.parse($('gym-config').textContent).resolutions || [];
    const prospectiveStrategies = [
      ['ema-trend', 'EMA trend'], ['sma-cross', 'SMA crossover'],
      ['sma-reversion', 'SMA reversion'], ['bollinger-reversion', 'Bollinger reversion'],
      ['ema-confirmed', 'EMA confirmed'], ['relative-momentum', 'Relative momentum'],
      ['rsi-rebound', 'RSI rebound'], ['macd-cross', 'MACD crossover'],
    ];
    const prospectiveOptions = (selected, optional = false) =>
      (optional ? '<option value="">' + text('Not selected', 'انتخاب نشده') + '</option>' : '') +
      prospectiveStrategies.map(([id, label]) => '<option value="' + esc(id) + '"' +
        (selected === id ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
    host.innerHTML = `<h2>${text('Research workspace', 'فضای پژوهش')}</h2>
      <p>${text('Recorded observations and paper decisions. Supplied account inputs remain unverified.', 'مشاهدات ثبت‌شده و تصمیمات آزمایشی؛ اطلاعات حساب ورودی تأییدشده نیست.')}</p>
      <details open><summary>${text('Guided paper research', 'پژوهش آزمایشی مرحله‌ای')}</summary>
        <p class="field-help">${text('Recorded quotes only. All outcomes remain hypothetical and disarmed. Future evaluation attempts consume their local registration once.', 'فقط قیمت‌های ثبت‌شده؛ همه نتایج فرضی و غیرفعال‌اند. تلاش ارزیابی آینده فقط یک بار از ثبت محلی استفاده می‌کند.')}</p>
        <form id="guided-research-form" class="ticket-fields">
          <label>${text('Research model', 'مدل پژوهش')}<select id="guided-model">
            <option value="premium-research">${text('TMN premium', 'صرف تومان')}</option><option value="lead-lag-research">${text('Lead / lag', 'تقدم / تأخر')}</option>
            <option value="twap-preview">${text('TWAP child preview', 'پیش‌نمایش TWAP')}</option></select></label>
          <label>${text('Primary symbol or base (premium: BTC)', 'نماد یا دارایی پایه (صرف: BTC)')}<input id="guided-symbol" required pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text('Leader symbol (lag only)', 'نماد پیشرو (فقط تقدم)')}<input id="guided-leader" value="ETHUSDT" pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text('From · UTC', 'از · UTC')}<input id="guided-from" type="datetime-local" required></label>
          <label>${text('To · UTC', 'تا · UTC')}<input id="guided-to" type="datetime-local" required></label>
          <label>${text('Fixed bar', 'بازهٔ ثابت')}<select id="guided-resolution">${resolutions.filter(x => x !== 'session').map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
          <label>${text('Max quote age (seconds)', 'حداکثر سن قیمت (ثانیه)')}<input id="guided-age" type="number" min="1" max="3600" value="120" required></label>
          <label>${text('Max alignment skew (seconds)', 'حداکثر اختلاف زمانی (ثانیه)')}<input id="guided-skew" type="number" min="0" max="3600" value="10" required></label>
          <label>${text('Fee fraction', 'نرخ کارمزد')}<input id="guided-fee" value="0.001" inputmode="decimal" required></label>
          <div id="guided-twap-fields" class="ticket-fields" hidden>
            <label>${text('Side', 'جهت')}<select id="guided-side"><option>BUY</option><option>SELL</option></select></label>
            <label>${text('Base quantity', 'مقدار پایه')}<input id="guided-quantity" value="1" inputmode="decimal"></label>
            <label>${text('Child slices', 'تعداد برش')}<input id="guided-slices" type="number" min="1" max="100" value="4"></label>
            <label>${text('Participation', 'سهم از عمق')}<input id="guided-participation" value="0.5" inputmode="decimal"></label>
            <label>${text('Available quote', 'موجودی ارز مظنه')}<input id="guided-cash" value="1000" inputmode="decimal"></label>
            <label>${text('Available base', 'موجودی دارایی پایه')}<input id="guided-base" value="0" inputmode="decimal"></label>
            <label>${text('Max delay (seconds)', 'حداکثر تأخیر (ثانیه)')}<input id="guided-delay" type="number" min="0" max="3600" value="10"></label>
          </div>
          <button class="button" type="submit">${text('Run paper diagnostic', 'اجرای بررسی آزمایشی')}</button>
        </form>
        <div id="guided-result" role="status" aria-live="polite"></div>
      </details>
      <details><summary>${text('Frozen prospective comparison · paper only', 'مقایسهٔ آیندهٔ ثبت‌شده · فقط آزمایشی')}</summary>
        <p class="field-help">${text('Freeze two to four strategy configurations before collecting future data. The window must start in the future. Registration cannot authorize capital or establish a profitable edge.', 'دو تا چهار پیکربندی راهبرد را پیش از جمع‌آوری داده‌های آینده ثبت ثابت کنید. بازه باید در آینده آغاز شود. این ثبت اجازهٔ سرمایه یا اثبات سودآوری نیست.')}</p>
        <form id="prospective-register-form" class="ticket-fields">
          <label>${text('Market symbol', 'نماد بازار')}<input id="prospective-symbol" pattern="[A-Z0-9]{2,24}" autocomplete="off" required dir="ltr" placeholder="BTCUSDT"></label>
          <label>${text('Selection cutoff · UTC', 'پایان انتخاب · UTC')}<input id="prospective-selection-end" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text('Future evaluation start · UTC', 'شروع ارزیابی آینده · UTC')}<input id="prospective-test-from" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text('Evaluation end · UTC (exclusive)', 'پایان ارزیابی · UTC (غیرشامل)')}<input id="prospective-test-to" type="datetime-local" step="60" required dir="ltr"></label>
          <label>${text('Fixed close resolution', 'بازهٔ بسته‌شدن ثابت')}<select id="prospective-resolution" required dir="ltr">${resolutions.filter(x => x !== 'session').map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
          <label>${text('Starting quote cash · exact decimal', 'موجودی آغازین ارز مظنه · اعشاری دقیق')}<input id="prospective-cash" value="1000" inputmode="decimal" required dir="ltr"></label>
          <label>${text('Fee fraction · exact decimal', 'نرخ کارمزد · اعشاری دقیق')}<input id="prospective-fee" value="0.001" inputmode="decimal" required dir="ltr"></label>
          <label>${text('Candidate A', 'گزینهٔ الف')}<select id="prospective-strategy-first" required>${prospectiveOptions('ema-trend')}</select></label>
          <label>${text('Candidate B', 'گزینهٔ ب')}<select id="prospective-strategy-second" required>${prospectiveOptions('sma-cross')}</select></label>
          <label>${text('Candidate C · optional', 'گزینهٔ پ · اختیاری')}<select id="prospective-strategy-third">${prospectiveOptions('', true)}</select></label>
          <label>${text('Candidate D · optional', 'گزینهٔ ت · اختیاری')}<select id="prospective-strategy-fourth">${prospectiveOptions('', true)}</select></label>
          <details><summary>${text('Optional strategy parameter overrides · JSON', 'تغییر اختیاری پارامترهای راهبرد · JSON')}</summary>
            <p class="field-help">${text('Leave blank to freeze native defaults. This advanced section is optional.', 'برای ثبت پیش‌فرض‌های اصلی خالی بگذارید. این بخش پیشرفته اختیاری است.')}</p>
            <label>${text('Candidate A parameters', 'پارامترهای گزینهٔ الف')}<textarea id="prospective-params-first" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text('Candidate B parameters', 'پارامترهای گزینهٔ ب')}<textarea id="prospective-params-second" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text('Candidate C parameters', 'پارامترهای گزینهٔ پ')}<textarea id="prospective-params-third" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
            <label>${text('Candidate D parameters', 'پارامترهای گزینهٔ ت')}<textarea id="prospective-params-fourth" rows="2" dir="ltr" spellcheck="false" placeholder="{}"></textarea></label>
          </details>
          <button class="button" type="submit">${text('Freeze future paper comparison', 'ثبت ثابت مقایسهٔ آزمایشی آینده')}</button>
        </form>
        <form id="prospective-evaluate-form" class="ticket-fields">
          <label>${text('Frozen registration ID · 64 hex characters', 'شناسهٔ ثبت ثابت · ۶۴ نویسهٔ شانزده‌شانزدهی')}<input id="prospective-id" pattern="[0-9a-f]{64}" maxlength="64" autocomplete="off" spellcheck="false" required dir="ltr"></label>
          <button id="prospective-inspect" type="button" class="button">${text('Inspect saved status · read only', 'بررسی وضعیت ثبت‌شده · فقط خواندنی')}</button>
          <label class="check"><input id="prospective-ack" type="checkbox">${text('I understand an evaluation attempt is consumed once, even if it fails. Inspect status before retrying anything.', 'می‌دانم تلاش ارزیابی حتی در صورت شکست فقط یک‌بار مصرف می‌شود. پیش از هر تکرار وضعیت را بررسی می‌کنم.')}</label>
          <button type="submit" class="button">${text('Consume one paper evaluation · no orders', 'اجرای یک‌بارهٔ ارزیابی آزمایشی · بدون سفارش')}</button>
        </form>
        <div id="prospective-result" role="status" aria-live="polite"></div>
      </details>
      <details open><summary>${text('Coverage timeline', 'خط زمانی پوشش داده')}</summary>
        <form id="coverage-form" class="ticket-fields">
          <label>${text('Symbol', 'نماد')}<input id="coverage-symbol" required pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text('From · UTC', 'از · UTC')}<input id="coverage-from" type="datetime-local" required></label>
          <label>${text('To · UTC', 'تا · UTC')}<input id="coverage-to" type="datetime-local" required></label>
          <label>${text('Resolution', 'بازه')}<select id="coverage-resolution">${resolutions.map(value => `<option>${esc(value)}</option>`).join('')}</select></label>
          <button class="button" type="submit">${text('Inspect coverage', 'بررسی پوشش')}</button></form><div id="coverage-timeline"></div></details>
      <details><summary>${text('Failed jobs and recovery', 'کارهای ناموفق و بازیابی')}</summary>
        <button id="recovery-refresh" class="button" type="button">${text('Load jobs', 'نمایش کارها')}</button>
        <label>${text('Recovery reason', 'دلیل بازیابی')}<input id="recovery-reason" maxlength="256"></label><div id="recovery-jobs"></div></details>
      <details><summary>${text('Decision replay', 'مرور تصمیمات')}</summary><form id="replay-form">
        <label>${text('Saved run ID', 'شناسه اجرای ذخیره‌شده')}<input id="replay-run" required pattern="[0-9a-f]{16}" dir="ltr"></label>
        <button class="button" type="submit">${text('Open replay', 'نمایش تصمیمات')}</button></form>
        <div class="actions"><button id="replay-previous" type="button" class="button" disabled>${text('Previous', 'قبلی')}</button><button id="replay-next" type="button" class="button" disabled>${text('Next', 'بعدی')}</button></div><div id="replay-decision"></div></details>
      <details><summary>${text('Evidence-linked AI research', 'پژوهش هوش مصنوعی با ارجاع به شواهد')}</summary>
        <p>${text('Prepare an evidence packet in the workbench below, inspect it here, then explicitly send it using a configured preset. Interpretations stay unverified. Validate and save returned notes with the workbench.', 'بسته شواهد را در کارگاه پایین آماده و اینجا بررسی کنید؛ ارسال فقط با انتخاب شما و الگوی تنظیم‌شده انجام می‌شود. تفسیرها تأییدشده نیستند. یادداشت خروجی را در کارگاه بررسی و ذخیره کنید.')}</p>
        <p id="research-packet-id" dir="ltr"></p><label>${text('Evidence prompt', 'متن شواهد')}<textarea id="research-packet-prompt" rows="5" readonly dir="ltr"></textarea></label>
        <label>${text('Configured AI preset ID', 'شناسه الگوی هوش مصنوعی')}<input id="research-packet-preset" maxlength="128" dir="ltr"></label>
        <button id="research-packet-send" class="button" type="button" disabled>${text('Send to AI · may incur charges', 'ارسال به هوش مصنوعی · ممکن است هزینه داشته باشد')}</button><pre id="research-packet-response" class="output" dir="auto"></pre></details>
      <p id="research-workspace-status" role="status"></p>`;
    const call = (action, value) => api('/api/research/action', {method: 'POST', body: JSON.stringify({action, value})}, 130000);
    async function act(button, fn) {
      button.disabled = true; $('research-workspace-status').textContent = text('Working…', 'در حال اجرا…');
      try { await fn(); if ($('research-workspace-status').textContent === text('Working…', 'در حال اجرا…')) $('research-workspace-status').textContent = text('Request completed.', 'درخواست انجام شد.'); }
      catch { $('research-workspace-status').textContent = text('Request failed. Refresh the saved state before retrying a mutation.', 'درخواست ناموفق بود. پیش از تکرار، وضعیت ذخیره‌شده را بازخوانی کنید.'); }
      finally { button.disabled = button.id === 'replay-previous' ? offset === 0 : button.id === 'replay-next' ? offset + 1 >= total : false; }
    }
    const json = value => `<pre class="output" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
    $('guided-model').onchange = () => {
      const twap = $('guided-model').value === 'twap-preview';
      $('guided-twap-fields').hidden = !twap;
      const hideLabel = (id, hidden) => {
        const label = $(id).closest?.('label');
        if (label) label.hidden = hidden;
      };
      hideLabel('guided-leader', $('guided-model').value !== 'lead-lag-research');
      hideLabel('guided-resolution', twap);
      hideLabel('guided-age', twap);
      hideLabel('guided-skew', twap);
    };
    $('guided-model').onchange();
    $('guided-research-form').onsubmit = event => { event.preventDefault(); act(event.target.querySelector('button'), async () => {
      const action = $('guided-model').value;
      const from = $('guided-from').value + ':00Z', to = $('guided-to').value + ':00Z';
      const common = {from, to};
      const value = action === 'premium-research'
        ? {...common, base: $('guided-symbol').value, resolution: $('guided-resolution').value,
           max_age_seconds: Number($('guided-age').value), max_skew_seconds: Number($('guided-skew').value), fee_rate: $('guided-fee').value}
        : action === 'lead-lag-research'
          ? {...common, primary: $('guided-symbol').value, leader: $('guided-leader').value,
             resolution: $('guided-resolution').value, max_age_seconds: Number($('guided-age').value),
             max_skew_seconds: Number($('guided-skew').value), min_overlap: 3}
          : {...common, symbol: $('guided-symbol').value, side: $('guided-side').value, quantity: $('guided-quantity').value,
             slices: Number($('guided-slices').value), participation: $('guided-participation').value,
             fee_rate: $('guided-fee').value, available_quote: $('guided-cash').value,
             available_base: $('guided-base').value, max_delay_seconds: Number($('guided-delay').value)};
      $('guided-result').textContent = '';
      const report = await call(action, value);
      const summary = action === 'premium-research' ? report.coverage : action === 'lead-lag-research'
        ? {status: report.status, overlap: report.overlap, correlation: report.correlation}
        : {requested: report.requested_quantity, filled: report.filled_quantity, cancelled: report.cancelled_quantity, children: report.children.length};
      $('guided-result').innerHTML = `<p><strong>${text('Paper only · no order submitted', 'فقط آزمایشی · هیچ سفارشی ثبت نشده')}</strong></p><p>${esc(JSON.stringify(summary))}</p><details><summary>${text('Inspect exact evidence', 'بررسی شواهد دقیق')}</summary>${json(report)}</details>`;
    }); };
    let prospectiveBusy = false;
    const prospectiveIdPattern = /^[0-9a-f]{64}$/;
    const prospectiveNumberPattern = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
    const prospectiveError = message => {
      $('prospective-result').textContent = message;
      $('research-workspace-status').textContent = message;
    };
    const prospectiveUtc = id => {
      const raw = $(id).value;
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) throw new Error(text('Enter valid UTC dates.', 'تاریخ‌های UTC معتبر وارد کنید.'));
      const stamp = raw + ':00Z';
      if (!Number.isFinite(Date.parse(stamp))) throw new Error(text('Invalid UTC date.', 'تاریخ UTC نامعتبر است.'));
      return stamp;
    };
    const prospectiveParams = id => {
      const raw = $(id).value.trim();
      if (!raw) return {};
      const params = JSON.parse(raw);
      if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error(text('Parameters must be a JSON object.', 'پارامترها باید شیء JSON باشند.'));
      return params;
    };
    const prospectiveEvidence = value => '<details><summary>' +
      text('Inspect exact saved evidence', 'بررسی شواهد دقیق ذخیره‌شده') + '</summary>' + json(value) + '</details>';
    const prospectiveShow = (action, result) => {
      if (action === 'prospective-register') {
        if (!prospectiveIdPattern.test(result.id || '')) throw new Error('Invalid registration receipt');
        $('prospective-id').value = result.id;
        $('prospective-result').innerHTML = '<p><strong>' +
          text('FROZEN · paper only · no funded authority', 'ثبت ثابت · فقط آزمایشی · بدون مجوز سرمایه') +
          '</strong></p><p dir="ltr"><code>' + esc(result.id) + '</code></p>' + prospectiveEvidence(result);
      } else if (action === 'prospective-status') {
        const consumed = (result.events || []).some(event => event.kind === 'PROSPECTIVE_ATTEMPT');
        $('prospective-result').innerHTML = '<p><strong>' +
          text(consumed ? 'Attempt already consumed · cannot retry' : 'Not yet consumed · inspect future window before evaluating',
               consumed ? 'تلاش مصرف شده است · تکرار نکنید' : 'هنوز مصرف نشده · پیش از ارزیابی بازهٔ آینده را بررسی کنید') +
          '</strong></p><p>' + esc(result.kind || 'UNKNOWN') + ' · ' + esc(result.id || '') +
          '</p>' + prospectiveEvidence(result);
      } else {
        const report = result.report || {};
        const candidates = report.configuration?.candidates || [];
        const rows = Array.isArray(report.rows) ? report.rows : [];
        const headings = [text('Candidate', 'گزینه'), text('Fills', 'پرشدن‌ها'),
          text('Net in quote currency', 'خالص به ارز مظنه'), text('Trade / coverage', 'معامله / پوشش')];
        const body = rows.map((row, index) => {
          const net = row.net_available && row.net != null ? esc(String(row.net)) : text('UNAVAILABLE', 'ناموجود');
          const trade = row.no_trade ? text('NO TRADE', 'بدون معامله') : text('Modeled trades', 'معاملات شبیه‌سازی‌شده');
          const coverage = String(row.qualified ?? 'UNKNOWN') + '/' + String(row.observations ?? 'UNKNOWN');
          return '<tr><td>' + esc(candidates[index]?.strategy || row.config_hash || 'UNKNOWN') +
            '</td><td>' + esc(String(row.fills ?? 'UNKNOWN')) + '</td><td dir="ltr">' + net +
            '</td><td>' + trade + ' · ' + esc(coverage) + '</td></tr>';
        }).join('');
        $('prospective-result').innerHTML = '<p><strong>' +
          text('One-time attempt recorded · paper only · no order submitted', 'تلاش یک‌باره ثبت شد · فقط آزمایشی · بدون سفارش') +
          '</strong></p><p>' + text(report.comparable ? 'Modeled comparisons available' : 'Incomplete coverage: not comparable',
          report.comparable ? 'مقایسه‌های شبیه‌سازی‌شده موجودند' : 'پوشش ناکامل: غیرقابل مقایسه') +
          '</p><div class="workspace-table"><table><thead><tr>' + headings.map(label => '<th>' + esc(label) + '</th>').join('') +
          '</tr></thead><tbody>' + body + '</tbody></table></div>' + prospectiveEvidence(result);
      }
    };
    const prospectiveCall = async (button, action, value) => {
      if (prospectiveBusy) return;
      prospectiveBusy = true; button.disabled = true;
      $('prospective-result').textContent = text('Reading or saving local paper evidence…', 'در حال خواندن یا ثبت شواهد آزمایشی محلی…');
      try {
        const result = await call(action, value);
        prospectiveShow(action, result);
        $('research-workspace-status').textContent = text('Paper workflow completed.', 'گردش‌کار آزمایشی انجام شد.');
      } catch (error) {
        // The shared API exposes bounded 4xx server validation text as error.detail,
        // not error.message. Do not display 5xx bodies or automatically retry.
        const detail = typeof error?.detail === 'string' && error.detail.trim()
          ? error.detail.slice(0, 240) : '';
        const guidance = action === 'prospective-evaluate'
          ? text('Outcome not confirmed. Inspect the saved ID before any further mutation; do not retry a consumed evaluation.',
            'نتیجه تأیید نشد. پیش از هر تغییر دیگر شناسه ثبت‌شده را بررسی کنید و ارزیابی مصرف‌شده را تکرار نکنید.')
          : action === 'prospective-register'
            ? text('Registration was not confirmed. Correct the inputs; if a previous ID exists, inspect it before retrying.',
              'ثبت تأیید نشد. ورودی‌ها را اصلاح کنید؛ اگر شناسهٔ قبلی دارید، پیش از تلاش دوباره آن را بررسی کنید.')
            : text('Could not read registration status. Verify the saved ID and retry this read-only inspection.',
              'وضعیت ثبت خوانده نشد. شناسهٔ ذخیره‌شده را بررسی کرده و این مشاهدهٔ فقط‌خواندنی را تکرار کنید.');
        prospectiveError(guidance + (detail ? ' · ' + detail : ''));
      } finally {
        prospectiveBusy = false; button.disabled = false;
      }
    };
    $('prospective-register-form').onsubmit = event => {
      event.preventDefault(); if (prospectiveBusy || event.target.reportValidity?.() === false) return;
      try {
        const selection_end = prospectiveUtc('prospective-selection-end');
        const test_from = prospectiveUtc('prospective-test-from');
        const test_to = prospectiveUtc('prospective-test-to');
        const selected = Date.parse(selection_end), from = Date.parse(test_from), to = Date.parse(test_to);
        if (!(selected <= Date.now() && Date.now() < from && from < to && to - from <= 31 * 86400000))
          throw new Error(text('Selection cutoff must be past; evaluation must be a disjoint future window of at most 31 days.',
            'پایان انتخاب باید در گذشته باشد و ارزیابی در بازه‌ای جدا در آینده با حداکثر ۳۱ روز انجام شود.'));
        const resolution = $('prospective-resolution').value;
        const units = /^([1-9][0-9]*)(min|h|day)$/.exec(resolution);
        const stepMs = units ? Number(units[1]) * {min: 60000, h: 3600000, day: 86400000}[units[2]] : NaN;
        if (!Number.isFinite(stepMs) || from - selected < stepMs || (to - from) / stepMs > 1440)
          throw new Error(text('Purge at least one fixed bar after selection; use at most 1440 evaluation closes.',
            'پس از انتخاب دست‌کم یک بازهٔ ثابت فاصله دهید؛ ارزیابی حداکثر ۱۴۴۰ بسته‌شدن دارد.'));
        const cash = $('prospective-cash').value.trim(), fee_rate = $('prospective-fee').value.trim();
        if (!prospectiveNumberPattern.test(cash) || /^0(?:\.0+)?$/.test(cash) || !prospectiveNumberPattern.test(fee_rate))
          throw new Error(text('Cash and fees must be nonnegative exact decimal strings; cash must be positive.',
            'موجودی و کارمزد باید رشته‌های اعشاری دقیق و نامنفی باشند؛ موجودی باید مثبت باشد.'));
        const candidates = [];
        for (const slot of ['first', 'second', 'third', 'fourth']) {
          const strategy = $('prospective-strategy-' + slot).value;
          if (strategy) candidates.push({strategy, params: prospectiveParams('prospective-params-' + slot)});
        }
        if (candidates.length < 2 || candidates.length > 4 || new Set(candidates.map(c => JSON.stringify(c))).size !== candidates.length)
          throw new Error(text('Select two to four distinct candidate configurations.', 'دو تا چهار پیکربندی متفاوت انتخاب کنید.'));
        const symbol = $('prospective-symbol').value.trim();
        if (!/^[A-Z0-9]{2,24}$/.test(symbol)) throw new Error(text('Enter a valid uppercase market symbol.', 'یک نماد بازار معتبر با حروف بزرگ وارد کنید.'));
        prospectiveCall(event.target.querySelector('button'), 'prospective-register',
          {symbol, candidates, selection_end, test_from, test_to, resolution, cash, fee_rate});
      } catch (error) { prospectiveError(error.message || text('Invalid registration.', 'ثبت نامعتبر است.')); }
    };
    const prospectiveSavedId = () => {
      const id = $('prospective-id').value.trim();
      if (!prospectiveIdPattern.test(id)) throw new Error(text('Enter a saved 64-character registration ID.', 'یک شناسهٔ ذخیره‌شدهٔ ۶۴ نویسه‌ای وارد کنید.'));
      return id;
    };
    $('prospective-inspect').onclick = event => {
      if (prospectiveBusy) return;
      try { prospectiveCall(event.target, 'prospective-status', prospectiveSavedId()); }
      catch (error) { prospectiveError(error.message); }
    };
    $('prospective-evaluate-form').onsubmit = event => {
      event.preventDefault();
      if (prospectiveBusy || event.target.reportValidity?.() === false) return;
      try {
        const id = prospectiveSavedId();
        if (!$('prospective-ack').checked) throw new Error(text('Explicit one-time evaluation acknowledgment is required.',
          'تأیید آگاهانهٔ ارزیابی یک‌باره الزامی است.'));
        $('prospective-ack').checked = false;
        prospectiveCall(event.target.querySelector('button[type="submit"]'), 'prospective-evaluate', id);
      } catch (error) { prospectiveError(error.message); }
    };
    $('coverage-form').onsubmit = event => { event.preventDefault(); act(event.target.querySelector('button'), async () => {
      const result = await call('coverage', {symbol: $('coverage-symbol').value, from: $('coverage-from').value + ':00Z', to: $('coverage-to').value + ':00Z', resolution: $('coverage-resolution').value});
      $('coverage-timeline').innerHTML = `<p>${esc(result.report_id)} · ${esc(JSON.stringify(result.counts))}</p><p>${esc(result.limitation)}</p><div class="workspace-table"><table><thead><tr>${['UTC', text('State', 'وضعیت'), text('Quotes', 'قیمت‌ها'), text('Late trades', 'معاملات دیررس'), text('Quote age (s)', 'عمر قیمت (ثانیه)'), text('Indicators', 'شاخص‌ها')].map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${result.buckets.map(row => `<tr><td dir="ltr">${esc(row.from)}</td><td>${esc(row.status)}</td><td>${esc(row.quotes)}</td><td>${esc(row.late_trade_receipts)}</td><td>${esc(row.last_known_qualified_quote_age_seconds ?? 'UNKNOWN')} ${row.quote_stale ? text('(STALE)', '(کهنه)') : ''}</td><td><details><summary>${text('Readiness', 'آمادگی')}</summary>${json(row.indicator_readiness)}</details></td></tr>`).join('')}</tbody></table></div>`;
    }); };
    async function jobs() {
      const result = await call('list', null);
      $('recovery-jobs').innerHTML = result.jobs.map((job, i) => `<article class="panel"><p dir="ltr">${esc(job.id)}</p><p>${esc(job.next_at)} · ${esc(job.last_report?.status ?? 'WAITING')}</p><div class="actions"><button type="button" class="button" data-job-index="${i}" data-recover="RETRY" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text('Allow retry', 'اجازه تلاش مجدد')}</button><button type="button" class="button" data-job-index="${i}" data-recover="SKIP" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text('Record skip of this window', 'ثبت صرف‌نظر از این بازه')}</button><button type="button" class="button" data-job-index="${i}" data-recover="CATCHUP" ${job.enabled ? '' : 'disabled'}>${text('Run up to 10 due windows', 'اجرای حداکثر ۱۰ بازه سررسیدشده')}</button></div></article>`).join('') || text('No scheduled jobs.', 'کاری زمان‌بندی نشده است.');
      $('recovery-jobs').querySelectorAll('article').forEach((panel, i) => {
        const report = result.jobs[i].last_report;
        if (report?.error_code) {
          const reason = document.createElement('p');
          reason.textContent = report.error_code === 'HYPOTHESIS_VERSION_UNAVAILABLE'
            ? text('This job requires an unavailable engine or strategy revision. Pause it and register a new version, or restore its original revision before retrying.', 'این کار به نسخه‌ای از موتور یا راهبرد نیاز دارد که در دسترس نیست. آن را متوقف و نسخه جدیدی ثبت کنید، یا پیش از تلاش مجدد نسخه اصلی را بازیابی کنید.')
            : report.message;
          panel.append(reason);
        }
        if (report?.status !== 'RUNNING') return;
        panel.insertAdjacentHTML('beforeend', json(report));
        const release = document.createElement('button');
        release.type = 'button'; release.className = 'button'; release.dataset.jobIndex = i; release.dataset.recover = 'INTERRUPT';
        release.textContent = text('Release this attempt · does not stop its process', 'آزادسازی این تلاش · فرایند آن متوقف نمی‌شود');
        panel.append(release);
      });
      $('recovery-jobs').querySelectorAll('button').forEach(button => { button.onclick = () => act(button, async () => {
        const job = result.jobs[Number(button.dataset.jobIndex)], action = button.dataset.recover;
        const response = action === 'INTERRUPT'
          ? await call('job-interrupt', {job_id: job.id, expected_due: job.next_at, expected_claim: job.last_report.claim_id, reason: $('recovery-reason').value})
          : action === 'CATCHUP' ? await call('job-catch-up', {job_id: job.id, limit: 10}) : await call('job-recover', {job_id: job.id, expected_due: job.next_at, action, reason: $('recovery-reason').value});
        await jobs(); $('research-workspace-status').textContent = JSON.stringify(response);
      }); });
    }
    $('recovery-refresh').onclick = event => act(event.target, jobs);
    let offset = 0, runId = '', total = 0, replayBusy = false, feature = '', annotationPending = null;
    async function replay() {
      if (replayBusy) return;
      replayBusy = true;
      try {
      const linkedOpen = $('replay-feature')?.closest('details')?.open ?? false;
      const notesOpen = $('replay-annotation-form')?.closest('details')?.open ?? false;
      const start = Math.max(0, offset - 149);
      const result = await call('replay', {run_id: runId, offset: start, limit: offset - start + 1}); total = result.total;
      const row = result.decisions.at(-1);
      $('replay-decision').innerHTML = row ? `<p>${offset + 1} / ${total} · ${esc(row.known_at_decision.t)} · ${esc(row.known_at_decision.action)}</p><h3>${text('Known at decision', 'اطلاعات هنگام تصمیم')}</h3><p>${esc((row.known_at_decision.reasons ?? []).join(' · '))}</p><p dir="ltr">${text('Bid / Ask', 'خرید / فروش')}: ${esc(row.known_at_decision.bid ?? 'UNKNOWN')} / ${esc(row.known_at_decision.ask ?? 'UNKNOWN')} · ${esc(row.known_at_decision.quote_time ?? 'UNKNOWN')}</p><h3>${text('Holdings before decision', 'دارایی پیش از تصمیم')}</h3><p>${esc(row.balance_status)}</p>${json(row.balances_before)}<details><summary>${text('Indicator values and readiness', 'مقدار و آمادگی شاخص‌ها')}</summary>${json(row.known_at_decision.feature_values)}</details><details><summary>${text('Recorded rules', 'قواعد ثبت‌شده')}</summary>${json(row.known_at_decision.rules_known)}</details><details><summary>${text('Bar and reference observations', 'مشاهدات شمع و مرجع')}</summary>${json({bar: row.known_at_decision.bar_known, context: row.known_at_decision.context_known, reference: row.known_at_decision.reference_known, skipped: row.known_at_decision.skipped})}</details><details><summary>${text('Later modeled order outcome · not known at decision', 'نتیجه بعدی سفارش شبیه‌سازی‌شده · هنگام تصمیم معلوم نبود')}</summary>${json(row.subsequent_modeled_order)}</details>` : text('No recorded decisions.', 'تصمیمی ثبت نشده است.');
      $('replay-decision').insertAdjacentHTML('afterbegin', window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa));
      if (row) {
        const features = Object.keys(row.known_at_decision.feature_values ?? {}).filter(key => {
          const value = row.known_at_decision.feature_values[key];
          return typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value));
        });
        if (!features.includes(feature)) feature = features[0] ?? '';
        $('replay-decision').insertAdjacentHTML('beforeend', `<details><summary>${text('Linked equity and indicator panes', 'نمودارهای مرتبط ارزش و شاخص')}</summary>${window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa, 'equity')}<label>${text('Recorded indicator', 'شاخص ثبت‌شده')}<select id="replay-feature">${features.map(key => `<option ${key === feature ? 'selected' : ''} value="${esc(key)}">${esc(key)}</option>`).join('')}</select></label><div id="replay-feature-chart"></div></details><details><summary>${text('Operator annotations · separate from decision evidence', 'یادداشت‌های کاربر · جدا از شواهد تصمیم')}</summary><form id="replay-annotation-form"><label>${text('Note on this decision', 'یادداشت این تصمیم')}<textarea id="replay-annotation-text" maxlength="2000" required></textarea></label><button class="button" type="submit">${text('Save annotation', 'ثبت یادداشت')}</button></form><div id="replay-annotations"></div><button id="replay-annotations-more" class="button" type="button" disabled>${text('More annotations', 'یادداشت‌های بیشتر')}</button></details>`);
        const featureChart = () => { $('replay-feature-chart').innerHTML = feature ? window.GymReplayChart.render(result.decisions, offset, result.quote_currency, esc, fa, feature) : text('No numeric indicator trace.', 'ردپای عددی شاخص موجود نیست.'); };
        $('replay-feature').onchange = event => { feature = event.target.value; featureChart(); }; featureChart();
        $('replay-feature').closest('details').open = linkedOpen;
        $('replay-annotation-form').closest('details').open = notesOpen;
        const identity = {run_id: result.run_id, outputs_digest: result.outputs_digest};
        let pageAfter = 0, pageThrough = null;
        async function notes() {
          const page = await call('annotation-list', {...identity, after: pageAfter, through: pageThrough, limit: 20});
          pageThrough = page.through; pageAfter = page.next_after;
          $('replay-annotations').insertAdjacentHTML('beforeend', page.events.map(note => `<article><button type="button" class="button" data-replay-index="${note.decision_index}">${esc(note.decision_at)}</button><p>${esc(note.text)}</p><small>${esc(note.recorded_at)} · ${esc(note.id)}</small></article>`).join(''));
          $('replay-annotations-more').disabled = pageAfter == null;
        }
        await notes();
        $('replay-annotations-more').onclick = async event => { await act(event.target, notes); event.target.disabled = pageAfter == null; };
        $('replay-annotation-form').onsubmit = event => {
          event.preventDefault();
          act(event.target.querySelector('button'), async () => {
            const value = {...identity, decision_index: row.index, text: $('replay-annotation-text').value};
            const source = JSON.stringify(value);
            if (annotationPending?.source !== source) annotationPending = {source, request_id: crypto.randomUUID().replaceAll('-', '')};
            await call('annotation-add', {...value, request_id: annotationPending.request_id});
            annotationPending = null; await replay();
          });
        };
      }
      $('replay-decision').onclick = event => {
        const point = event.target.closest('[data-replay-index]');
        if (point && !replayBusy) act($('replay-form').querySelector('button'), async () => { offset = Number(point.dataset.replayIndex); await replay(); });
      };
      $('replay-decision').onkeydown = event => {
        const point = event.target.closest('[data-replay-index]');
        if (replayBusy || !point || !['Enter', ' ', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        act($('replay-form').querySelector('button'), async () => {
          offset = Math.max(0, Math.min(total - 1, Number(point.dataset.replayIndex) + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0)));
          await replay(); $('replay-decision').querySelector(`[data-replay-index="${offset}"]`)?.focus();
        });
      };
      $('replay-previous').disabled = offset === 0; $('replay-next').disabled = offset + 1 >= total;
      } finally { replayBusy = false; }
    }
    $('replay-form').onsubmit = event => { event.preventDefault(); if (replayBusy) return; runId = $('replay-run').value; offset = 0; act(event.target.querySelector('button'), replay); };
    $('replay-previous').onclick = event => { if (!replayBusy) act(event.target, async () => { offset = Math.max(0, offset - 1); await replay(); event.target.disabled = offset === 0; }); };
    $('replay-next').onclick = event => { if (!replayBusy) act(event.target, async () => { offset = Math.min(total - 1, offset + 1); await replay(); event.target.disabled = offset + 1 >= total; }); };
    $('research-packet-send').onclick = event => act(event.target, async () => {
      const preset = $('research-packet-preset').value.trim(); if (!preset) throw new Error('preset required');
      const response = await api('/api/models', {method: 'POST', body: JSON.stringify({action: 'complete', value: {preset, prompt: $('research-packet-prompt').value}})}, 150000);
      $('research-packet-response').textContent = JSON.stringify(response, null, 2);
    });
  }
  return { mount };
})();
