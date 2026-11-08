/* Explicit operator intent only; no polling, retries or automatic approval. */
window.gymNativeReview = (() => {
  let mounted = false;
  let pending = false;
  function mount(api, demo = false) {
    if (mounted) return;
    mounted = true;
    const form = document.getElementById('native-review-form');
    const context = document.getElementById('native-review-context');
    const submit = document.getElementById('native-review-submit');
    const output = document.getElementById('native-review-result');
    if (demo) {
      context.disabled = submit.disabled = true;
      output.textContent = document.documentElement.lang === 'fa' ? 'بررسی سرویس حفاظت‌شده در حالت نمایشی غیرفعال است.' : 'Protected operator reviews are disabled in DEMO.';
      return;
    }
    async function run(request) {
      if (pending) return;
      pending = true;
      context.disabled = submit.disabled = true;
      output.textContent = '';
      try {
        const result = await request();
        if (result.funded_authority !== false || result.order_submitted !== false) throw new Error('unsupported authority');
        output.textContent = JSON.stringify(result, null, 2);
      } catch (_) {
        output.textContent = document.documentElement.lang === 'fa'
          ? 'دریافت رسید تأیید نشد. پیش از تلاش دوباره، همان شناسه را بررسی کنید؛ وضعیت سفارش یا مجوز معامله اثبات نشده است.'
          : 'Receipt unacknowledged. Inspect the same identity before retrying; no order status or trading permission is established.';
      } finally { pending = false; context.disabled = submit.disabled = false; }
    }
    context.addEventListener('click', () => run(() => api('/api/operator-reviews', {}, 9000)));
    form.addEventListener('submit', event => {
      event.preventDefault();
      return run(() => api('/api/operator-reviews', {method:'POST', body:JSON.stringify(JSON.parse(document.getElementById('native-review-input').value))}, 9000));
    });
  }
  return {mount};
})();
