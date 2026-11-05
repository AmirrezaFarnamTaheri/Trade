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
  const idActions = new Set(['outcome-add', 'final-status', 'final-run', 'experiment-status']);
  actions['strategy-audit'] = ['Check causality and warm-up', 'بررسی علیت و دورهٔ آماده‌سازی', 'symbol, strategy, params, from, to, resolution, cash, fee_rate, latency_ms, checkpoints: [time], history_starts: [time]'];
  actions['return-bootstrap'] = ['Explore saved return uncertainty', 'بررسی عدم‌قطعیت بازده ثبت‌شده', 'run_id, seed, simulations, mean_block_length, max_gap_seconds'];
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
      $('research-action-result').textContent = '';
      try {
        const action = $('research-action').value;
        const input = $('research-action-input').value;
        const value = !actions[action][2] ? null : idActions.has(action) ? input.trim() : JSON.parse(input);
        const result = await api('/api/research/action', { method: 'POST', body: JSON.stringify({ action, value }) }, 130000);
        $('research-action-result').textContent = JSON.stringify(result, null, 2);
        if (action === 'research-packet') {
          $('research-packet-prompt').value = result.prompt;
          $('research-packet-id').textContent = result.packet.id;
          $('research-packet-send').disabled = false;
        }
      } catch { $('research-action-status').textContent = fa ? 'نتیجه دریافت نشد. ممکن است عملیات ثبت شده باشد؛ پیش از تکرار، ورودی و وضعیت ذخیره‌شده را بررسی کنید. ارزیابی مصرف‌شده را تکرار نکنید.' : 'Result was not delivered. The operation may have committed; inspect the input and saved state before retrying. Do not repeat a consumed evaluation.'; }
      finally { submit.disabled = false; }
    };
  }
  function workspace(api, esc, fa) {
    let host = $('research-workspace');
    if (!host) {
      host = document.createElement('section'); host.id = 'research-workspace'; host.className = 'panel';
      $('research-workbench').before(host);
    }
    const text = (en, persian) => fa ? persian : en;
    host.innerHTML = `<h2>${text('Research workspace', 'فضای پژوهش')}</h2>
      <p>${text('Recorded observations and paper decisions. Supplied account inputs remain unverified.', 'مشاهدات ثبت‌شده و تصمیمات آزمایشی؛ اطلاعات حساب ورودی تأییدشده نیست.')}</p>
      <details open><summary>${text('Coverage timeline', 'خط زمانی پوشش داده')}</summary>
        <form id="coverage-form" class="ticket-fields">
          <label>${text('Symbol', 'نماد')}<input id="coverage-symbol" required pattern="[A-Z0-9]{2,24}" dir="ltr"></label>
          <label>${text('From · UTC', 'از · UTC')}<input id="coverage-from" type="datetime-local" required></label>
          <label>${text('To · UTC', 'تا · UTC')}<input id="coverage-to" type="datetime-local" required></label>
          <label>${text('Resolution', 'بازه')}<select id="coverage-resolution"><option>1min</option><option>15min</option><option>1h</option><option>1day</option></select></label>
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
      button.disabled = true; $('research-workspace-status').textContent = '';
      try { await fn(); }
      catch { $('research-workspace-status').textContent = text('Request failed. Refresh the saved state before retrying a mutation.', 'درخواست ناموفق بود. پیش از تکرار، وضعیت ذخیره‌شده را بازخوانی کنید.'); }
      finally { button.disabled = button.id === 'replay-previous' ? offset === 0 : button.id === 'replay-next' ? offset + 1 >= total : false; }
    }
    const json = value => `<pre class="output" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
    $('coverage-form').onsubmit = event => { event.preventDefault(); act(event.target.querySelector('button'), async () => {
      const result = await call('coverage', {symbol: $('coverage-symbol').value, from: $('coverage-from').value + ':00Z', to: $('coverage-to').value + ':00Z', resolution: $('coverage-resolution').value});
      $('coverage-timeline').innerHTML = `<p>${esc(result.report_id)} · ${esc(JSON.stringify(result.counts))}</p><p>${esc(result.limitation)}</p><div class="workspace-table"><table><thead><tr>${['UTC', text('State', 'وضعیت'), text('Quotes', 'قیمت‌ها'), text('Late trades', 'معاملات دیررس'), text('Quote age (s)', 'عمر قیمت (ثانیه)'), text('Indicators', 'شاخص‌ها')].map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${result.buckets.map(row => `<tr><td dir="ltr">${esc(row.from)}</td><td>${esc(row.status)}</td><td>${esc(row.quotes)}</td><td>${esc(row.late_trade_receipts)}</td><td>${esc(row.last_known_qualified_quote_age_seconds ?? 'UNKNOWN')} ${row.quote_stale ? text('(STALE)', '(کهنه)') : ''}</td><td><details><summary>${text('Readiness', 'آمادگی')}</summary>${json(row.indicator_readiness)}</details></td></tr>`).join('')}</tbody></table></div>`;
    }); };
    async function jobs() {
      const result = await call('list', null);
      $('recovery-jobs').innerHTML = result.jobs.map((job, i) => `<article class="panel"><p dir="ltr">${esc(job.id)}</p><p>${esc(job.next_at)} · ${esc(job.last_report?.status ?? 'WAITING')}</p><div class="actions"><button type="button" class="button" data-job-index="${i}" data-recover="RETRY" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text('Allow retry', 'اجازه تلاش مجدد')}</button><button type="button" class="button" data-job-index="${i}" data-recover="SKIP" ${job.last_report?.status === 'FAILED' ? '' : 'disabled'}>${text('Record skip of this window', 'ثبت صرف‌نظر از این بازه')}</button><button type="button" class="button" data-job-index="${i}" data-recover="CATCHUP" ${job.enabled ? '' : 'disabled'}>${text('Run up to 10 due windows', 'اجرای حداکثر ۱۰ بازه سررسیدشده')}</button></div></article>`).join('') || text('No scheduled jobs.', 'کاری زمان‌بندی نشده است.');
      $('recovery-jobs').querySelectorAll('article').forEach((panel, i) => {
        const report = result.jobs[i].last_report;
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
