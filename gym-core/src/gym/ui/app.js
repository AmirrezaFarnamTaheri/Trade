const { demo: DEMO, resolutions: FIXED_RESOLUTIONS = [] } = JSON.parse(document.getElementById("gym-config").textContent);
// The per-run key arrives once in the URL fragment, which browsers never send to the server, and stays in this tab.
let TOKEN = (() => {
  const match = /^#t=([A-Za-z0-9_-]{16,128})$/.exec(location.hash);
  try {
    if (match) { sessionStorage.setItem("gym-token", match[1]); history.replaceState(null, "", location.pathname + location.search); }
    return match?.[1] || sessionStorage.getItem("gym-token") || "";
  } catch (_) { return match?.[1] || ""; }
})();
// A private link pasted into an already-open tab only changes the fragment; reload so the key is read.
addEventListener("hashchange", () => { if (/^#t=[A-Za-z0-9_-]{16,128}$/.test(location.hash)) location.reload(); });

const vocabulary = {
  workspaceCapabilities: ["Workspace capabilities", "قابلیت‌های محیط کار"],
  venueCatalogue: ["Full venue catalogue", "فهرست کامل بازارهای صرافی"],
  catalogueNote: ["The market search also filters this list. Listing is separate from data collection, paper eligibility and execution permission.", "جست‌وجوی بازار این فهرست را هم فیلتر می‌کند. فهرست‌شدن با گردآوری داده، صلاحیت آزمایشی و مجوز اجرا متفاوت است."],
  collectionMode: ["Collection mode", "حالت گردآوری"],
  "all-spot": ["All listed spot assets · TMN / USDT", "همهٔ دارایی‌های نقدی فهرست‌شده · تومان / تتر"],
  "ranked-spot": ["Ranked non-risk-flagged spot assets · TMN / USDT", "دارایی‌های نقدی رتبه‌بندی‌شده بدون پرچم ریسک · تومان / تتر"],
  paperSides: ["Paper buy / sell", "خرید / فروش آزمایشی"],
  paperSidesNote: ["Spot · 1× · buy, then sell owned assets; no borrowed positions", "نقدی · ۱ برابر · خرید و فروش دارایی موجود؛ بدون موقعیت قرضی"],
  financingScope: ["Leverage / short selling", "اهرم / فروش استقراضی"],
  financingScopeNote: ["Margin LONG / SHORT: public venue rules, collateral checks, previews and local paper replay in Paper research. Trade credit: supplied-debt diagnostics. Live borrowing and order submission remain unavailable.", "تعهدی لانگ / شورت: قواعد عمومی صرافی، بررسی وثیقه، پیش‌نمایش و بازپخش محلی در پژوهش آزمایشی. اعتبار معاملاتی: تحلیل با بدهی ورودی. قرض‌گیری و ارسال سفارش واقعی در دسترس نیست."],
  decisionTimeframes: ["Paper decision timeframes", "بازه‌های تصمیم آزمایشی"],
  candleFetchTimeframes: ["Venue candle fetch timeframes", "بازه‌های دریافت شمع صرافی"],
  timeframeSourceNote: ["Paper bars use received observations. New timeframes do not create missing history; research requires recorded data. Live order submission is unavailable.", "شمع آزمایشی از مشاهدات دریافتی ساخته می‌شود. بازهٔ جدید تاریخچهٔ مفقود را ایجاد نمی‌کند؛ پژوهش به دادهٔ ثبت‌شده نیاز دارد. ارسال سفارش واقعی در دسترس نیست."],
  collectionCapacity: ["Asset collection capacity", "ظرفیت گردآوری دارایی"],
  listedPairs: ["Listed pairs", "بازارهای فهرست‌شده"],
  collectionState: ["Collection state", "وضعیت گردآوری"],
  riskFlag: ["Venue risk flag", "پرچم ریسک صرافی"],
  OBSERVING: ["Observing", "در حال مشاهده"],
  REMOVED_BY_OPERATOR: ["Removed by operator", "حذف‌شده توسط کاربر"],
  NOT_SPOT: ["Outside spot collection", "خارج از گردآوری نقدی"],
  UNSUPPORTED_QUOTE: ["Outside TMN / USDT collection", "خارج از گردآوری تومان / تتر"],
  RISK_FILTER: ["Excluded by ranked-mode risk filter", "حذف‌شده با فیلتر ریسک در حالت رتبه‌بندی"],
  NOT_SELECTED: ["Outside configured watch selection", "خارج از فهرست مشاهدهٔ تنظیم‌شده"],
  navModels: ["AI connections", "اتصال‌های هوش مصنوعی"],
  skipToContent: ["Skip to content", "رفتن به محتوا"],
  observedDepth: ["Observed book depth", "عمق مشاهده‌شدهٔ دفتر سفارش"],
  depthNote: ["Quantities within 10 / 25 / 50 bps of mid use only received levels. They do not establish full-book depth or executable capacity.", "حجم‌های فاصلهٔ ۱۰، ۲۵ و ۵۰ واحد پایه از میانه فقط از ردیف‌های دریافت‌شده‌اند؛ عمق کامل یا ظرفیت اجرای سفارش را اثبات نمی‌کنند."],
  depthBand: ["Band (bps)", "فاصله (واحد پایه)"],
  bidDepth: ["Bid quantity", "حجم خرید"], askDepth: ["Ask quantity", "حجم فروش"],
  imbalance: ["Base-quantity imbalance", "عدم تعادل حجم دارایی"],
  exportSummary: ["Download paper summary", "دریافت خلاصهٔ آزمایشی"],
  exportHtml: ["Download offline HTML report", "دریافت گزارش HTML آفلاین"],
  savePreview: ["Save preview to offline journal", "ذخیرهٔ پیش‌نمایش در دفتر آفلاین"],
  acknowledgeOffline: ["Acknowledge offline", "تأیید مشاهدهٔ آفلاین"],
  rejectOffline: ["Reject offline", "رد آفلاین"],
  journalSaved: ["Saved in offline journal", "در دفتر آفلاین ذخیره شد"],
  reviewWriteError: ["Journal write failed. Refresh the journal before retrying; the ticket may have expired or already been reviewed.", "ثبت ناموفق بود. پیش از تلاش دوباره دفتر را تازه کنید؛ ممکن است سفارش منقضی یا قبلاً بررسی شده باشد."],
  summaryNote: ["Includes run fingerprints, valuation, modeled costs and sampled drawdown. Private notes and account records are excluded.", "شامل شناسه‌های اجرا، ارزش‌گذاری، هزینه‌های فرضی و افت نمونه‌برداری‌شده است؛ یادداشت خصوصی و سوابق حساب در آن نیست."],
  sampledDrawdown: ["Sampled maximum drawdown", "بیشترین افت در نمونه‌ها"],
  drawdownNote: ["Measured from starting cash and recorded equity marks, including the end estimate. Missing intervals can hide larger losses.", "از سرمایهٔ اولیه و ارزش‌های ثبت‌شده، شامل برآورد انتهایی، محاسبه شده است. فاصله‌های بدون داده می‌توانند زیان بزرگ‌تری را پنهان کنند."],
  recordedObservations: ["Recorded observations", "مشاهدات ثبت‌شده"],
  title: ["TradingGYM · Agent workspace", "تریدینگ‌جیم · محیط عامل معاملاتی"],
  appTagline: ["Autonomous agent workspace", "محیط عامل معاملاتی خودکار"],
  navigation: ["Workspace navigation", "ناوبری محیط"],
  navResearchGroup: ["Agent research", "پژوهش عامل"],
  navObserveGroup: ["Observe & prepare", "مشاهده و آماده‌سازی"],
  navWorkspaceGroup: ["Workspace", "محیط کار"],
  navMarkets: ["Markets", "بازارها"], navResearch: ["Paper research", "پژوهش آزمایشی"],
  navAccount: ["Account journal", "دفتر حساب"], navOperate: ["Offline ticket", "سفارش آفلاین"],
  navRules: ["Venue rules", "قواعد صرافی"], navHealth: ["System health", "سلامت سیستم"],
  disarmedStatus: ["Trading is disarmed", "معامله غیرفعال است"],
  sidebarSafety: ["Observe, research, and preview. No autonomous orders.", "مشاهده، پژوهش و پیش‌نمایش. بدون سفارش خودکار."],
  localWorkspace: ["Local workspace", "محیط محلی"], workspace: ["Agent workspace", "محیط عامل"],
  demoLabel: ["Demo workspace", "محیط نمایشی"],
  demoBanner: ["Synthetic market data. Research results cannot justify real capital.", "داده‌های ساختگی بازار. نتایج پژوهش مجوز استفاده از سرمایهٔ واقعی نیست."],
  sessionKeyMissing: ["This tab has no session key. Open the link printed by gymctl run.", "این زبانه کلید نشست ندارد. پیوندی را که gymctl run چاپ می‌کند باز کنید."],
  connectionError: ["Data could not be refreshed. Previously loaded values may be out of date.", "به‌روزرسانی داده‌ها ممکن نشد. مقادیر قبلی ممکن است قدیمی باشند."],
  retry: ["Retry", "تلاش دوباره"], observatory: ["Agent observatory", "رصدخانهٔ عامل"],
  marketsTitle: ["The market, in view.", "بازار، پیش روی شما."],
  marketsLead: ["Inspect the market and constraints your autonomous agent must understand.", "بازار و محدودیت‌هایی را بررسی کنید که عامل خودکار باید درک کند."],
  refresh: ["Refresh data", "به‌روزرسانی داده‌ها"], marketWatch: ["Market watch", "دیده‌بان بازار"],
  observationOnly: ["Observation only", "فقط مشاهده"], filterPlaceholder: ["Search pair or asset", "جست‌وجوی جفت‌ارز یا دارایی"],
  quoteFilter: ["Filter by quote currency", "فیلتر ارز مظنه"], quoteAll: ["All pairs", "همهٔ جفت‌ها"],
  pair: ["Market", "بازار"], bid: ["Bid", "بهترین خرید"], ask: ["Ask", "بهترین فروش"],
  spreadBps: ["Spread · bps", "اسپرد · واحد پایه"], lastTrade: ["Last trade", "آخرین معامله"],
  bookAge: ["Quote quality", "کیفیت مظنه"], entry: ["Buy / entry", "خرید / ورود"], exit: ["Sell / exit", "فروش / خروج"],
  loading: ["Loading workspace…", "در حال بارگذاری محیط…"],
  pairHint: ["Select a market to inspect its rules and order-book quantities.", "برای بررسی قواعد و حجم‌های دفتر سفارش، یک بازار را انتخاب کنید."],
  marketNote: ["TMN prices are in toman. Rule eligibility is separate from execution permission; live trading remains disabled.", "قیمت‌های TMN به تومان است. مجاز بودن طبق قواعد، مجوز اجرا نیست؛ معاملهٔ واقعی غیرفعال می‌ماند."],
  researchEyebrow: ["Evaluate the agent", "ارزیابی عامل"], researchTitle: ["Paper research", "پژوهش آزمایشی"],
  researchLead: ["Evaluate saved agent runs, compare costs, and trace every decision.", "اجراهای ذخیره‌شدهٔ عامل را ارزیابی کنید، هزینه‌ها را بسنجید و هر تصمیم را دنبال کنید."],
  paperOnly: ["Paper results only", "فقط نتایج آزمایشی"], paperRuns: ["Saved runs", "اجراهای ذخیره‌شده"],
  runFilter: ["Filter by symbol", "صافی بر اساس نماد"], loadMoreRuns: ["Load more runs", "نمایش اجراهای بیشتر"], accountEyebrow: ["Your observation journal", "دفتر مشاهدات شما"],
  accountTitle: ["Account journal", "دفتر حساب"],
  accountLead: ["Recorded balances and external orders, with their source and limitations.", "موجودی‌های ثبت‌شده و سفارش‌های خارجی، همراه با منبع و محدودیت‌ها."],
  readOnly: ["Read-only", "فقط خواندنی"], accountRead: ["Venue account (read-only)", "حساب صرافی (فقط خواندنی)"],
  externalHistory: ["External order observations (unverified)", "مشاهدات سفارش‌های خارجی (تأییدنشده)"],
  offlineReviewTitle: ["Offline ticket reviews (no funded approval)", "بررسی سفارش‌های آفلاین (بدون مجوز سرمایه)"],
  offlineEyebrow: ["Prepare without placing an order", "آماده‌سازی بدون ارسال سفارش"], operateTitle: ["Offline ticket", "سفارش آفلاین"],
  operateWarning: ["Estimate costs against a bounded snapshot. No order is submitted and no capital is authorized.", "هزینه را با یک تصویر محدود از بازار برآورد کنید. هیچ سفارشی ارسال و هیچ سرمایه‌ای مجاز نمی‌شود."],
  disarmed: ["Disarmed", "غیرفعال"], offlineTicketTitle: ["Dry-run order ticket", "فرم سفارش آزمایشی"],
  loadExample: ["Load synthetic example", "بارگذاری نمونهٔ ساختگی"], ticketJson: ["Snapshot & order request · JSON", "تصویر بازار و درخواست سفارش · JSON"],
  offlineTicketHelp: ["Use exact decimal strings for amounts. This quote-fee model checks a BUY entry or SELL exit against declared limits.", "مبلغ‌ها را به صورت رشتهٔ اعشاری دقیق بنویسید. این مدل با فرض کارمزد در ارز مظنه، ورود BUY یا خروج SELL را با سقف‌های اعلام‌شده می‌سنجد."],
  previewOffline: ["Preview costs", "پیش‌نمایش هزینه‌ها"],
  ticketPrivacy: ["Local preview. Keep credentials out of this field.", "پیش‌نمایش محلی است. اطلاعات ورود را در این کادر وارد نکنید."],
  protectionHeading: ["Protection & authority", "حفاظت و مجوز"],
  protectionNote: ["Account observations are not spendable cash. An offline preview cannot activate the executor or certify venue stops.", "مشاهدهٔ حساب، موجودی قابل خرج نیست. پیش‌نمایش آفلاین نمی‌تواند اجراگر را فعال یا توقف‌های صرافی را تأیید کند."],
  rulesEyebrow: ["Know the constraints", "شناخت محدودیت‌ها"], rulesTitle: ["Venue rules", "قواعد صرافی"],
  rulesLead: ["Review closures, quotas, and the evidence behind each restriction.", "تعطیلی‌ها، سهمیه‌ها و شواهد هر محدودیت را بررسی کنید."],
  exportRules: ["Export JSON", "دریافت JSON"], loadPreset: ["Load October 2026 preset", "بارگذاری الگوی اکتبر ۲۰۲۶"],
  importTitle: ["Import a rule set", "ورود مجموعهٔ قواعد"],
  importHelp: ["Paste a JSON list of rules. Malformed rules are quarantined and never applied.", "فهرست قواعد را در قالب JSON وارد کنید. قواعد نامعتبر قرنطینه می‌شوند و اعمال نخواهند شد."],
  importRules: ["Import rules", "ورود قواعد"], healthEyebrow: ["Behind the observations", "پشت صحنهٔ مشاهدات"],
  healthTitle: ["System health", "سلامت سیستم"],
  healthLead: ["Check collection, data quality, and the evidence still missing.", "گردآوری، کیفیت داده و شواهدی را بررسی کنید که هنوز فراهم نیست."],
  errorsTitle: ["Collector events", "رویدادهای گردآورنده"],
  venueFactsTitle: ["Venue capability evidence (read-only)", "شواهد قابلیت‌های صرافی (فقط خواندنی)"],
  qualityTitle: ["Recent quality observations", "مشاهدات اخیر کیفیت"], chaosTitle: ["Simulated venue checks", "آزمون‌های صرافی شبیه‌سازی‌شده"],
  footerPurpose: ["Autonomous agent research & observation", "پژوهش و مشاهدهٔ عامل خودکار"],
  footerAuthority: ["Local data. No live execution.", "دادهٔ محلی. بدون اجرای واقعی."],
  lightTheme: ["Light mode", "حالت روشن"], darkTheme: ["Dark mode", "حالت تیره"],
  requestError: ["The local service could not complete this request.", "سرویس محلی نتوانست این درخواست را انجام دهد."],
  observedPairs: ["Observed pairs", "جفت‌های تحت مشاهده"], observedPairsNote: ["In the current collector universe", "در فهرست فعلی گردآورنده"],
  healthyQuotes: ["Healthy quotes", "مظنه‌های معتبر"], healthyQuotesNote: ["Present quotes without disqualifying flags", "مظنهٔ موجود، بدون پرچم نامعتبرکننده"],
  eligibleEntries: ["Rule-eligible entries", "ورودهای مجاز طبق قواعد"], eligibleEntriesNote: ["Rules only · execution disabled", "فقط طبق قواعد · اجرا غیرفعال است"],
  showing: ["Showing", "نمایش"], of: ["of", "از"], pairs: ["pairs", "جفت"], updated: ["Updated", "به‌روزرسانی"],
  noMarkets: ["No markets observed yet", "هنوز بازاری مشاهده نشده است"],
  noMarketsHelp: ["The collector has not provided a market catalog. Refresh after it has connected.", "گردآورنده هنوز فهرست بازار را ارائه نکرده است. پس از اتصال، دوباره به‌روزرسانی کنید."],
  noMatches: ["No matching markets", "بازار منطبقی پیدا نشد"], noMatchesHelp: ["Try another asset name or choose All pairs.", "نام دارایی دیگری را جست‌وجو کنید یا همهٔ جفت‌ها را انتخاب کنید."],
  fxLabel: ["USDT valuation factor", "نرخ ارزش‌گذاری تتر"], fxNote: ["Mid quote · TMN per USDT · not an executable price", "میانهٔ مظنه · تومان به ازای تتر · قیمت قابل اجرا نیست"],
  fxClosed: ["Stale · market closed", "قدیمی · بازار تعطیل است"], liveQuote: ["Live quote", "مظنهٔ جاری"],
  unavailable: ["Unavailable", "در دسترس نیست"], unknown: ["Unknown", "نامعلوم"], none: ["—", "—"],
  healthy: ["Qualified", "معتبر"], quoteMissing: ["No quote", "بدون مظنه"], seconds: ["s", "ثانیه"],
  eligible: ["Rule-eligible", "مجاز طبق قواعد"], blocked: ["Blocked", "مسدود"], notEvaluated: ["Not evaluated", "ارزیابی نشده"],
  noBlockers: ["No rule blockers reported. This does not permit execution.", "مانعی از قواعد گزارش نشده است. این وضعیت مجوز اجرا نیست."],
  blockers: ["Rule blockers", "موانع طبق قواعد"], warnings: ["Warnings & limitations", "هشدارها و محدودیت‌ها"],
  nextRuleChange: ["Next rule change", "تغییر بعدی قواعد"], noRuleChange: ["No scheduled rule change in the next 7 days", "تغییر برنامه‌ریزی‌شده‌ای برای ۷ روز آینده وجود ندارد"],
  changeNote: ["A scheduled change is not a promise that trading will become eligible.", "تغییر برنامه‌ریزی‌شده تضمین نمی‌کند که معامله مجاز شود."],
  quotaRemaining: ["Remaining rule quota · USDT", "سهمیهٔ باقی‌مانده طبق قواعد · تتر"],
  source: ["Source", "منبع"], confirmed: ["Last confirmed", "آخرین تأیید"], reason: ["Reason", "دلیل"],
  classification: ["Class", "رده"], status: ["Status", "وضعیت"], family: ["Family", "خانواده"],
  bestBidQuantity: ["Quantity at best bid", "حجم بهترین خرید"], bestAskQuantity: ["Quantity at best ask", "حجم بهترین فروش"],
  absoluteSpread: ["Spread in quote currency", "اسپرد در ارز مظنه"], ruleVersion: ["Rule set version", "نسخهٔ مجموعهٔ قواعد"],
  unitEpoch: ["Unit epoch", "نسخهٔ واحد"], pairDetails: ["Market details", "جزئیات بازار"],
  feedConnected: ["Collector connected", "گردآورنده متصل است"], feedDisconnected: ["Collector disconnected", "گردآورنده قطع است"],
  feedStopped: ["Collector stopped", "گردآورنده متوقف است"], feedUnknown: ["Collector status pending", "در انتظار وضعیت گردآورنده"],
  refreshFailed: ["Refresh failed · data may be stale", "به‌روزرسانی ناموفق · احتمال دادهٔ قدیمی"],
  frameAge: ["Last frame age", "سن آخرین پیام"], synthetic: ["Synthetic", "ساختگی"], liveData: ["Observed data", "دادهٔ مشاهده‌شده"],
  noRuns: ["Your agent's evidence starts here", "شواهد عامل از اینجا آغاز می‌شود"],
  noRunsHelp: ["Create a saved paper run to inspect its costs, baseline comparison, and decision trail. Nothing here authorizes real capital.", "یک اجرای آزمایشی ذخیره کنید تا هزینه‌ها، مقایسه با مبنا و مسیر تصمیم‌ها را ببینید. هیچ بخش این صفحه مجوز سرمایهٔ واقعی نیست."],
  demoRunHelp: ["For a synthetic example, run these commands from gym-core, then refresh:", "برای نمونهٔ ساختگی، این فرمان‌ها را در پوشهٔ gym-core اجرا و سپس صفحه را به‌روزرسانی کنید:"],
  selectRun: ["Select a saved run to inspect its results.", "برای بررسی نتایج، یک اجرای ذخیره‌شده را انتخاب کنید."],
  runReadError: ["This run could not be loaded. Refresh or select another saved run.", "بارگذاری این اجرا ممکن نشد. به‌روزرسانی کنید یا اجرای دیگری را انتخاب کنید."],
  equity: ["Closing equity", "ارزش پایانی"], net: ["Net result", "نتیجهٔ خالص"], fills: ["Filled orders", "سفارش‌های پرشده"],
  observations: ["Qualified observations", "مشاهدات معتبر"], strategy: ["Strategy", "راهبرد"],
  equityCurve: ["Paper equity", "ارزش سبد آزمایشی"], curveNote: ["Marked at the observed bid. Chart geometry is approximate; values retain source precision.", "ارزش‌گذاری با خرید مشاهده‌شده. شکل نمودار تقریبی است؛ مقادیر با دقت منبع نمایش داده می‌شوند."],
  noCurve: ["No equity observations in this run.", "این اجرا مشاهده‌ای برای ارزش سبد ندارد."],
  costWaterfall: ["From gross to net", "از ناخالص تا خالص"], directional: ["Directional result", "نتیجهٔ تغییر قیمت"],
  spread: ["Spread cost", "هزینهٔ اسپرد"], fees: ["Fees", "کارمزد"], latency_drift: ["Latency drift", "اثر تأخیر"],
  noCost: ["No closing cost breakdown is available.", "تفکیک هزینهٔ پایانی در دسترس نیست."],
  baselineTitle: ["Matched baselines", "مبناهای هم‌شرایط"], baselineNote: ["Same window, initial cash, and cost assumptions.", "بازه، سرمایهٔ اولیه و فرض‌های هزینه یکسان‌اند."],
  usdtEquivalent: ["Net · USDT-equivalent", "خالص · معادل تتر"],
  rankingTitle: ["Active strategy ranking", "رتبه‌بندی راهبردهای فعال"], rankingNote: ["USDT-equivalent. Zero-trade runs remain visible as abstainers.", "بر اساس معادل تتر. اجراهای بدون معامله به‌صورت جداگانه باقی می‌مانند."],
  rank: ["Rank", "رتبه"], abstainers: ["Abstainers · no filled trades", "بدون فعالیت · بدون معاملهٔ پرشده"],
  noActiveRank: ["No active result with a USDT-equivalent valuation.", "نتیجهٔ فعالی با ارزش‌گذاری معادل تتر موجود نیست."],
  evidenceTitle: ["Economic evidence", "شواهد اقتصادی"], noCapital: ["No capital authorized", "هیچ سرمایه‌ای مجاز نیست"],
  roundTrips: ["Completed round trips", "رفت‌وبرگشت‌های کامل"], claimCeiling: ["Claim ceiling", "حد ادعای مجاز"],
  evidenceGate: ["Capital gate eligible", "واجد شرایط دروازهٔ سرمایه"],
  noEvidence: ["No evidence report is attached. This run cannot authorize trading.", "گزارش شواهدی پیوست نشده است. این اجرا نمی‌تواند مجوز معامله بدهد."],
  reportDetails: ["Report details & recorded operator decisions", "جزئیات گزارش و تصمیم‌های ثبت‌شدهٔ کاربر"],
  runInputs: ["Run inputs & session", "ورودی‌ها و نشست اجرا"],
  lastDecisions: ["Last 100 decisions", "۱۰۰ تصمیم آخر"], decisionHelp: ["Newest first. The decision log holds each snapshot, mark and matching paper order.", "جدیدترین در بالا. گزارش تصمیمات شامل هر تصویر لحظه‌ای، نشانه‌گذاری و سفارش آزمایشی مرتبط است."],
  noDecisions: ["No strategy decisions were recorded.", "تصمیمی از راهبرد ثبت نشده است."],
  fullRecord: ["Full record", "رکورد کامل"], accountNotConfigured: ["No account observation configured", "مشاهدهٔ حساب پیکربندی نشده است"],
  accountSetupHelp: ["Private account observations are not configured on this server. Market observation and paper research work without an account; never paste credentials here.", "مشاهدات خصوصی حساب در این سرور پیکربندی نشده است. مشاهدهٔ بازار و پژوهش آزمایشی به حساب نیاز ندارند؛ اطلاعات ورود را اینجا وارد نکنید."],
  accountObserved: ["Observed · unverified · unmanaged", "مشاهده‌شده · تأییدنشده · مدیریت‌نشده"],
  accountError: ["Account observation unavailable. Previously shown balances have been cleared.", "مشاهدهٔ حساب در دسترس نیست. موجودی‌های قبلی از نمایش پاک شده‌اند."],
  accountBalance: ["Observed balances", "موجودی‌های مشاهده‌شده"],
  accountBalanceNote: ["Venue values and locked amounts are observations, not spendable or protectable balances.", "مقدار و مبلغ بلوکه‌شدهٔ صرافی فقط مشاهده‌اند؛ موجودی قابل خرج یا قابل حفاظت نیستند."],
  serviceReceipts: ["Service observation receipts", "رسیدهای مشاهدهٔ سرویس"],
  accountFeeRates: ["Recorded fee rates", "نرخ‌های ثبت‌شدهٔ کارمزد"],
  accountFeeNote: ["Rates are decimal fractions: 0.001 means 0.1%. Actual charged fees remain unreconciled.", "نرخ‌ها به‌صورت اعشاری‌اند: ۰٫۰۰۱ یعنی ۰٫۱٪. کارمزد واقعی کسرشده هنوز تطبیق داده نشده است."],
  makerFeeRate: ["Maker rate", "نرخ سفارش‌گذار"], takerFeeRate: ["Taker rate", "نرخ سفارش‌بردار"],
  noAccountFees: ["No fee rates recorded.", "نرخ کارمزدی ثبت نشده است."],
  serviceReceiptsNote: ["These saved references record when the service received balances, fees and orders. They may be stale; this local copy does not independently verify the protected journal or grant trading permission.", "این ارجاع‌های ذخیره‌شده زمان دریافت موجودی، کارمزد و سفارش‌ها توسط سرویس را ثبت می‌کنند. ممکن است قدیمی باشند؛ این نسخهٔ محلی صحت دفتر محافظت‌شده را مستقلاً تأیید نمی‌کند و مجوز معامله نمی‌دهد."],
  receiptBalances: ["Balances", "موجودی‌ها"], receiptFees: ["Fees", "کارمزدها"], receiptOrder: ["Order observation", "مشاهدهٔ سفارش"],
  receiptOpenOrders: ["Open-order page", "صفحهٔ سفارش‌های باز"], receiptHistory: ["Order-history page", "صفحهٔ تاریخچهٔ سفارش‌ها"],
  orderPages: ["Observed order pages", "صفحه‌های مشاهده‌شدهٔ سفارش"],
  orderPagesNote: ["Each page is a separate observation. Empty pages do not prove absence; completeness, atomicity and settlement remain unverified.", "هر صفحه مشاهده‌ای جداگانه است. خالی بودن صفحه نبودن سفارش را ثابت نمی‌کند؛ کامل بودن، هم‌زمانی و تسویه تأیید نشده‌اند."],
  pageNumber: ["Page", "صفحه"], perPage: ["Requested page size", "اندازهٔ درخواستی صفحه"],
  paginationEcho: ["Venue page echo", "بازتاب صفحه در پاسخ صرافی"], MATCHED: ["Matches request", "مطابق درخواست"],
  UNVERIFIED: ["Unverified", "تأیید نشده"],
  receiptEntry: ["Journal entry", "رویداد دفتر"], receiptReceived: ["Received", "دریافت"],
  receiptRequested: ["Requested", "درخواست"], receiptRuntime: ["Service run", "اجرای سرویس"],
  receiptGeneration: ["Credential version", "نسخهٔ کلید"], receiptRequest: ["Request reference", "ارجاع درخواست"],
  receiptResponse: ["Response fingerprint", "اثر انگشت پاسخ"], receiptEvent: ["Journal fingerprint", "اثر انگشت دفتر"],
  asset: ["Asset", "دارایی"], venueValue: ["Venue value", "مقدار صرافی"], venueLocked: ["Locked", "بلوکه‌شده"],
  accountOrders: ["External / manual orders", "سفارش‌های خارجی / دستی"], clientId: ["Client ID", "شناسهٔ سفارش کاربر"],
  rawStatus: ["Venue status", "وضعیت صرافی"], settlement: ["Settlement", "تسویه"], filledObserved: ["Observed filled amount", "مقدار پرشدهٔ مشاهده‌شده"],
  orderDetails: ["Recorded order and fill details", "جزئیات ثبت‌شدهٔ سفارش و اجراها"],
  orderDetailsNote: ["Reported fills and fee currencies are observations. Matching quantities do not prove cash settlement; missing fills remain unknown.", "اجراها و ارز کارمزد، مشاهدات گزارش‌شده‌اند. تطابق مقدار، تسویهٔ وجه را ثابت نمی‌کند؛ اجراهای ناموجود نامعلوم می‌مانند."],
  requestedQuantity: ["Requested quantity", "مقدار درخواستی"], fillPrice: ["Reported fill price", "قیمت گزارش‌شدهٔ اجرا"],
  fillFee: ["Reported fee", "کارمزد گزارش‌شده"], fillFeeAsset: ["Fee asset", "دارایی کارمزد"],
  fillTimestamp: ["Venue timestamp (raw)", "زمان صرافی (خام)"], noReportedFills: ["No reported fill details", "جزئیات اجرا گزارش نشده است"],
  fillCoverage: ["Fill coverage", "پوشش اجراها"], REPORTED_QUANTITY_MATCHES: ["Reported quantities match", "مقدارهای گزارش‌شده تطابق دارند"],
  noBalances: ["No balances in this snapshot.", "در این تصویر موجودی ثبت نشده است."],
  noAccountOrders: ["No external orders in this snapshot. Absence does not prove settlement.", "در این تصویر سفارش خارجی نیست. نبودن سفارش، تسویه را ثابت نمی‌کند."],
  accountExposure: ["External exposure · unmanaged", "تعهدات خارجی · مدیریت‌نشده"], product: ["Product", "محصول"],
  obligation: ["Observed obligation", "تعهد مشاهده‌شده"], account: ["Account", "حساب"],
  noExposure: ["No external exposure recorded.", "تعهد خارجی ثبت نشده است."],
  externalEmpty: ["No external order observations recorded.", "مشاهده‌ای از سفارش خارجی ثبت نشده است."],
  externalNote: ["External observations are unverified. Filled amounts and missing orders never prove settlement.", "مشاهدات خارجی تأییدنشده‌اند. مقدار پرشده و نبودن سفارش، هرگز تسویه را ثابت نمی‌کند."],
  externalReadError: ["External order journal unavailable.", "دفتر سفارش‌های خارجی در دسترس نیست."],
  offlineReviewEmpty: ["No offline reviews recorded. Previews do not grant funded approval.", "بررسی آفلاینی ثبت نشده است. پیش‌نمایش مجوز سرمایه نیست."],
  offlineReviewReadError: ["Offline review journal unavailable.", "دفتر بررسی آفلاین در دسترس نیست."],
  previewHash: ["Preview fingerprint", "اثر انگشت پیش‌نمایش"],
  offlineTicketError: ["Ticket rejected. Check the documented fields, exact decimal strings, quote age, expiry, and declared limits. No order was submitted.", "درخواست پذیرفته نشد. فیلدهای مستند، رشته‌های اعشاری دقیق، سن مظنه، انقضا و سقف‌ها را بررسی کنید. هیچ سفارشی ارسال نشد."],
  offlineTicketResult: ["Offline preview · no order submitted", "پیش‌نمایش آفلاین · بدون ارسال سفارش"],
  previewBusy: ["Checking snapshot…", "در حال بررسی تصویر بازار…"],
  syntheticExample: ["Synthetic example loaded. All prices and balances are invented; edit the snapshot before evaluating your own scenario.", "نمونهٔ ساختگی بارگذاری شد. همهٔ قیمت‌ها و موجودی‌ها فرضی‌اند؛ برای سناریوی خود، تصویر بازار را ویرایش کنید."],
  quantity: ["Quantity", "مقدار"], expectedGross: ["Estimated gross quote", "مظنهٔ ناخالص برآوردی"], worstGross: ["Worst gross quote", "مظنهٔ ناخالص بدترین حالت"],
  worstFee: ["Worst quote fee", "کارمزد مظنه در بدترین حالت"], worstSpend: ["Maximum modeled quote spend", "بیشترین خرج مظنهٔ مدل‌شده"],
  worstProceeds: ["Minimum modeled quote proceeds", "کمترین دریافتی مظنهٔ مدل‌شده"], breakEven: ["Modeled break-even bid", "خرید سربه‌سر مدل‌شده"],
  quoteFeeOnly: ["Quote-fee assumption is unverified. This is a calculation against declared input, not a live executable quote.", "فرض کارمزد در ارز مظنه تأییدنشده است. این محاسبه بر اساس ورودی اعلام‌شده است و مظنهٔ واقعی قابل اجرا نیست."],
  mode: ["Mode", "حالت"], protection: ["Protection", "حفاظت"], venue_stops: ["Venue stops", "توقف‌های صرافی"],
  entries_enabled: ["Entries enabled", "ورود فعال است"], autopilot_enabled: ["Autopilot enabled", "عامل خودکار فعال است"],
  funded_authority: ["Funded authority", "مجوز سرمایه"], executor_state_verified: ["Executor state verified", "وضعیت اجراگر تأیید شده"],
  protectionUnavailable: ["Protection status unavailable. Trading remains disarmed; no execution authority can be inferred.", "وضعیت حفاظت در دسترس نیست. معامله غیرفعال می‌ماند؛ نمی‌توان مجوز اجرا را نتیجه گرفت."],
  yes: ["Yes", "بله"], no: ["No", "خیر"], state: ["State", "حالت"],
  rulesEmpty: ["No venue rules configured", "قاعده‌ای برای صرافی پیکربندی نشده است"],
  rulesEmptyHelp: ["An empty rule set is not permission to trade. Import reviewed rules or inspect the dated preset before loading it.", "خالی بودن قواعد مجوز معامله نیست. قواعد بررسی‌شده را وارد کنید یا پیش از بارگذاری، الگوی تاریخ‌دار را بررسی کنید."],
  disable: ["Disable", "غیرفعال کردن"],
  disableConfirm: ["Disable this rule? This changes the local rule ledger and subsequent eligibility checks:", "این قاعده غیرفعال شود؟ این کار دفتر قواعد محلی و بررسی‌های بعدی را تغییر می‌دهد:"],
  presetConfirm: ["Load the October 2026 USDT/TMN preset? It writes a historical preset to the local ledger and replaces rules with matching IDs. Review its dates and evidence before relying on it.", "الگوی اکتبر ۲۰۲۶ تتر/تومان بارگذاری شود؟ این الگوی تاریخی در دفتر محلی نوشته می‌شود و قواعد هم‌شناسه را جایگزین می‌کند. پیش از اتکا، تاریخ‌ها و شواهد آن را بررسی کنید."],
  ruleSaved: ["Rule disabled in the local ledger.", "قاعده در دفتر محلی غیرفعال شد."], presetSaved: ["Dated preset loaded. Review its effective dates and evidence.", "الگوی تاریخ‌دار بارگذاری شد. تاریخ اعتبار و شواهد آن را بررسی کنید."],
  ruleWriteError: ["Rule change failed. Refresh the ledger and try again.", "تغییر قاعده ناموفق بود. دفتر را به‌روزرسانی کنید و دوباره تلاش کنید."],
  importError: ["Import failed. Use a JSON list of rule objects, each with an id; check required rule fields.", "ورود ناموفق بود. فهرست JSON از اشیای قاعده با شناسهٔ id وارد و فیلدهای ضروری را بررسی کنید."],
  imported: ["imported", "وارد شد"], quarantined: ["quarantined", "قرنطینه شد"], effective: ["Effective window", "بازهٔ اعتبار"],
  blocksNow: ["Blocks now", "موانع فعلی"], nothing: ["None reported", "گزارش نشده"], history: ["Rule history & source JSON", "تاریخچهٔ قاعده و JSON منبع"],
  quarantineNote: ["Quarantined · not applied", "قرنطینه‌شده · اعمال نمی‌شود"],
  connected: ["Connection", "اتصال"], reconnects: ["Reconnects", "اتصال‌های مجدد"], qualityEvents: ["Recent quality events", "رویدادهای اخیر کیفیت"],
  connectedValue: ["Connected", "متصل"], disconnectedValue: ["Disconnected", "قطع"],
  noCollectorEvents: ["No collector errors reported. This does not certify data quality or trading readiness.", "خطایی از گردآورنده گزارش نشده است. این وضعیت کیفیت داده یا آمادگی معامله را تأیید نمی‌کند."],
  noQualityEvents: ["No recent quality observations recorded.", "مشاهدهٔ کیفیتی اخیراً ثبت نشده است."],
  time: ["Time · Tehran", "زمان · تهران"], instrument: ["Instrument", "ابزار"], flag: ["Flag", "پرچم"], detail: ["Detail", "جزئیات"],
  venueFactsEmpty: ["No venue capability evidence configured. Trading remains disabled.", "شواهدی برای قابلیت‌های صرافی پیکربندی نشده است. معامله غیرفعال می‌ماند."],
  venueFactsInfo: ["Evidence only · unverified origin. No order method or automated trading is certified.", "فقط شواهد · منبع تأییدنشده. هیچ روش سفارش یا معاملهٔ خودکاری تأیید نشده است."],
  venueFactsError: ["Venue capability evidence unavailable.", "شواهد قابلیت‌های صرافی در دسترس نیست."],
  capability: ["Capability", "قابلیت"], evidenceId: ["Evidence ID", "شناسهٔ شواهد"],
  chaosNotRun: ["No simulation report yet. Create one with gym-chaos; simulation does not certify the venue.", "هنوز گزارش شبیه‌سازی موجود نیست. با gym-chaos گزارش بسازید؛ شبیه‌سازی صرافی را تأیید نمی‌کند."],
  chaosError: ["Simulation report unavailable or unreadable.", "گزارش شبیه‌سازی در دسترس یا خوانا نیست."],
  chaosNote: ["Simulated fixtures only · no venue contact or capital authority.", "فقط سناریوهای شبیه‌سازی‌شده · بدون اتصال صرافی یا مجوز سرمایه."],
  simulationPassed: ["Simulation passed", "شبیه‌سازی موفق بود"], simulationFailed: ["Simulation failed", "شبیه‌سازی ناموفق بود"],
  fixture: ["Fixture", "سناریو"], runs: ["Runs", "اجراها"], settled: ["Settled", "تسویه‌شده"], frozen: ["Frozen", "متوقف"],
  violations: ["Violations", "نقض‌ها"], exampleTrace: ["Example trace", "مسیر نمونه"],
  STALE: ["Stale", "قدیمی"], CROSSED: ["Crossed book", "دفتر متقاطع"], ZERO_SPREAD: ["Zero spread", "اسپرد صفر"],
  NON_FINITE: ["Non-finite quote", "مظنهٔ نامتناهی"], NON_POSITIVE: ["Non-positive quote", "مظنهٔ غیرمثبت"],
  THIN_BOOK: ["Thin book", "دفتر کم‌عمق"], WIDE_SPREAD: ["Wide spread", "اسپرد زیاد"],
  DISARMED: ["Disarmed", "غیرفعال"], UNAVAILABLE: ["Unavailable", "در دسترس نیست"],
  NOT_CERTIFIED: ["Not certified", "تأیید نشده"], UNKNOWN: ["Unknown", "نامعلوم"],
  active: ["Active", "فعال"], disabled: ["Disabled", "غیرفعال"], scheduled: ["Scheduled", "برنامه‌ریزی‌شده"],
  expired: ["Expired", "منقضی"], stale: ["Stale · review needed", "قدیمی · نیازمند بررسی"],
};
Object.assign(vocabulary, {
  navOverview: ["Overview", "نمای کلی"], navSafety: ["Safety", "ایمنی"], navBackups: ["Backups", "پشتیبان‌ها"],
  overviewTitle: ["Operator workspace", "محیط اپراتور"], overviewLead: ["Follow your agent from market observation to research and preparation.", "عامل خود را از مشاهدهٔ بازار تا پژوهش و آماده‌سازی دنبال کنید."],
  missionSequence: ["Mission sequence", "مسیر فعالیت"], evidenceNotPermission: ["Evidence is not permission.", "شواهد، مجوز اجرا نیست."],
  stageObserve: ["Observe", "مشاهده"], stageObserveHelp: ["Market data & venue state", "دادهٔ بازار و وضعیت صرافی"], stageResearch: ["Research", "پژوهش"], stageResearchHelp: ["Paper runs & evidence", "اجراهای آزمایشی و شواهد"],
  stagePrepare: ["Prepare", "آماده‌سازی"], stagePrepareHelp: ["Offline tickets & costs", "سفارش آفلاین و هزینه‌ها"], stageValidate: ["Validate", "اعتبارسنجی"], stageValidateHelp: ["Inspect limitations", "بررسی محدودیت‌ها"],
  stageSafeguard: ["Safeguard", "حفاظت"], stageSafeguardHelp: ["Review missing protection", "بررسی حفاظت‌های تکمیل‌نشده"], stageExecute: ["Execute · locked", "اجرا · قفل"], stageExecuteHelp: ["No funded authority", "بدون مجوز سرمایه"],
  openMarkets: ["Open markets", "نمایش بازارها"], openResearch: ["Open research", "نمایش پژوهش"], openTicket: ["Prepare an offline ticket", "آماده‌سازی سفارش آفلاین"],
  safetyAuthority: ["Safety & authority", "ایمنی و مجوز"], recentEvidence: ["Recent evidence", "شواهد اخیر"], knownConstraints: ["Known constraints", "محدودیت‌های شناخته‌شده"],
  separateAuthority: ["Separate authorities", "مجوزهای مستقل"], separateAuthorityHelp: ["Observation, simulation, and execution are independent.", "مشاهده، شبیه‌سازی و اجرا مستقل‌اند."],
  unverifiedAccount: ["External observations", "مشاهدات خارجی"], unverifiedAccountHelp: ["Balances are not spendable executor cash; terminal order status is not settlement.", "موجودی مشاهده‌شده پول قابل خرج مجری نیست؛ وضعیت نهایی سفارش به معنی تسویه نیست."],
  exactPrecision: ["Exact precision", "دقت کامل"], exactPrecisionHelp: ["Monetary values retain their source decimal precision.", "مقادیر پولی با دقت اعشاری منبع نمایش داده می‌شوند."],
  safetyLead: ["Check the boundary between research and autonomous execution.", "مرز پژوهش و اجرای خودکار را بررسی کنید."], missingGates: ["Execution gates still open", "پیش‌نیازهای تکمیل‌نشدهٔ اجرا"],
  executorGate: ["The browser cannot attest to the privileged executor service.", "مرورگر نمی‌تواند سرویس مجری دارای دسترسی ویژه را تأیید کند."], stopsGate: ["No certified protective venue stops are connected.", "هیچ توقف حفاظتی تأییدشدهٔ صرافی متصل نیست."], authorityGate: ["Offline previews and paper evidence cannot arm trading.", "پیش‌نمایش آفلاین و شواهد آزمایشی نمی‌توانند معامله را فعال کنند."],
  installationCeiling: ["Installation capital limit", "سقف سرمایهٔ نصب"],
  nativeReviewTitle: ["Protected operator intent", "قصد اپراتور در سرویس حفاظت‌شده"],
  nativeReviewHelp: ["Requires the reviewed Windows service and helper to be installed. Records or revokes exact operator intent without sending orders. Holdings, fees and method qualification remain unverified.", "سرویس ویندوز و ابزار بررسی‌شده باید نصب باشند. قصد دقیق اپراتور را بدون ارسال سفارش ثبت یا لغو می‌کند. موجودی، کارمزد و تأیید روش همچنان اثبات نشده‌اند."],
  nativeReviewContext: ["Read service context", "خواندن وضعیت سرویس"], nativeReviewInput: ["Explicit native request (JSON)", "درخواست صریح سرویس (JSON)"],
  nativeReviewFields: ["Actions: status, inspect, approve, prepare, revoke. Prepare consumes an exact review once; it sends no order and reserves no money. Use the current client_id and expected_sequence. No credentials belong here.", "عملیات: status، inspect، approve، prepare، revoke. آماده‌سازی، بررسی دقیق را فقط یک بار مصرف می‌کند؛ سفارشی ارسال و پولی رزرو نمی‌شود. از client_id و expected_sequence فعلی استفاده کنید. اطلاعات ورود را اینجا وارد نکنید."],
  nativeReviewSubmit: ["Run protected review", "اجرای بررسی حفاظت‌شده"],
  ceilingConsoleHelp: ["After installing the reviewed helper, inspect the recorded limit in an administrator console. Changing it requires administrator authorization; increases require a different account from the operator.", "پس از نصب ابزار بررسی‌شده، سقف ثبت‌شده را در کنسول مدیر بررسی کنید. تغییر آن به مجوز مدیر نیاز دارد؛ افزایش سقف باید از حسابی جدا از اپراتور انجام شود."],
  ceilingUnverified: ["No service limit is verified by this page. Recording a limit does not arm trading or certify protection.", "این صفحه سقف سرویس را تأیید نمی‌کند. ثبت سقف، معامله را فعال نمی‌کند و به معنای تأیید حفاظت نیست."],
  backupLead: ["Encrypted ledger recovery uses the existing protected-console workflow.", "بازیابی رمزگذاری‌شدهٔ دفتر از مسیر کنسول حفاظت‌شده انجام می‌شود."],
  backupReceipts: ["Local recovery receipts", "رسیدهای محلی بازیابی"],
  noBackupReceipts: ["No completed backup or restore receipt recorded in this workspace.", "رسید پشتیبان یا بازیابی تکمیل‌شده‌ای در این محیط ثبت نشده است."],
  backupReceiptScope: ["Recorded operations only. Current archive availability and separate-machine recovery are unverified.", "فقط عملیات ثبت‌شده؛ موجود بودن فعلی بایگانی و بازیابی روی دستگاه جدا تأیید نشده است."],
  backupWorkflow: ["Create an encrypted backup", "ساخت پشتیبان رمزگذاری‌شده"], backupHelp: ["Use a pre-existing directory on an independent mounted volume. Enter the recovery passphrase only in the protected console.", "از پوشهٔ موجود روی دیسک مستقل استفاده کنید. عبارت بازیابی را فقط در کنسول حفاظت‌شده وارد کنید."],
  restoreWorkflow: ["Restore to a new ledger", "بازیابی در دفتر جدید"], restoreHelp: ["The destination must not exist. Restoration verifies the ledger and leaves execution disarmed.", "مقصد نباید وجود داشته باشد. بازیابی دفتر را بررسی می‌کند و اجرا غیرفعال می‌ماند."], recoveryTruth: ["Recovery evidence", "شواهد بازیابی"],
  integrityFirst: ["Integrity before use", "صحت‌سنجی پیش از استفاده"], integrityHelp: ["A successful decrypt is not trading permission. Signed manifest checks require an independently pinned public key.", "رمزگشایی موفق مجوز معامله نیست. بررسی مانیفست امضاشده به کلید عمومی مستقل و از پیش تعیین‌شده نیاز دارد."],
  privacy: ["Privacy", "حریم خصوصی"], backupPrivacy: ["Recovery passphrases and venue credentials never belong in a browser form.", "عبارت بازیابی و اطلاعات ورود صرافی را هرگز در فرم مرورگر وارد نکنید."],
  structuredForm: ["Structured form", "فرم ساختاریافته"], jsonEditor: ["JSON editor", "ویرایشگر JSON"], ticketEditor: ["Ticket editor", "ویرایشگر سفارش"],
  symbol: ["Symbol", "نماد"], side: ["Side", "جهت"], intent: ["Intent", "هدف"], worst_price: ["Worst price", "قیمت بدترین حالت"], fee_rate: ["Fee rate", "نرخ کارمزد"], operator_quote_cap: ["Operator quote cap", "سقف ارز مظنهٔ اپراتور"],
  available_quote: ["Declared quote balance", "موجودی اعلامی ارز مظنه"], available_base: ["Declared base balance", "موجودی اعلامی ارز پایه"], minimum_quote: ["Minimum quote notional", "حداقل ارزش سفارش"],
  observed_at: ["Observed at · zoned ISO", "زمان مشاهده · ISO با منطقه"], expires_at: ["Expires at · zoned ISO", "زمان انقضا · ISO با منطقه"], snapshot_seq: ["Snapshot sequence", "شمارهٔ تصویر"], quote_age_ms: ["Quote age · ms (0–2000)", "سن مظنه · میلی‌ثانیه (۰ تا ۲۰۰۰)"],
  previewChanged: ["Ticket changed. Preview again to calculate costs for these inputs.", "سفارش تغییر کرد. برای محاسبهٔ هزینهٔ این ورودی‌ها دوباره پیش‌نمایش بگیرید."],
  BUY: ["Buy", "خرید"], SELL: ["Sell", "فروش"], ENTRY: ["Entry", "ورود"], EXIT: ["Exit", "خروج"],
  savedRunCount: ["Saved paper runs", "اجراهای آزمایشی ذخیره‌شده"], runCountNote: ["Latest 50 records", "۵۰ رکورد آخر"],
  compareTitle: ["Compare paper strategies", "مقایسهٔ راهبردهای آزمایشی"],
  compareHelp: ["Both accounts use the same stored window, quotes, close snapshots, cash and costs. No execution proposals or orders.", "هر دو حساب از بازه، مظنه‌ها، تصاویر بسته‌شدن، سرمایه و هزینه‌های یکسان استفاده می‌کنند. بدون پیشنهاد اجرایی یا سفارش."],
  compareAction: ["Run matched comparison", "اجرای مقایسهٔ همسان"], comparing: ["Comparing…", "در حال مقایسه…"],
  compareCostNote: ["Fee 0.001 = 0.1% per fill. Latency: 500 ms. Point-in-time venue rules.", "کارمزد ۰٫۰۰۱ برابر ۰٫۱٪ هر معامله است. تأخیر: ۵۰۰ میلی‌ثانیه. قواعد صرافی در زمان رویداد."],
  windowFrom: ["From · UTC", "از · UTC"], windowTo: ["To · UTC (exclusive)", "تا · UTC (بدون نقطهٔ پایان)"],
  decisionResolution: ["Decision close", "بازهٔ بسته‌شدن برای تصمیم"], startingCash: ["Starting quote cash", "سرمایهٔ اولیهٔ ارز مظنه"],
  feeFraction: ["Fee per fill · fraction", "کارمزد هر معامله · کسر اعشاری"], firstCandidate: ["First candidate", "گزینهٔ اول"], secondCandidate: ["Second candidate", "گزینهٔ دوم"],
  coverageTitle: ["Stored coverage", "پوشش دادهٔ ذخیره‌شده"], coverageGaps: ["Gaps over 120 seconds", "وقفه‌های بیش از ۱۲۰ ثانیه"],
  coverageNote: ["Stored observations are not proof of a continuous paper session. Gaps are not filled in.", "داده‌های ذخیره‌شده اثبات اجرای پیوستهٔ آزمایشی نیستند. وقفه‌ها با دادهٔ ساختگی پر نمی‌شوند."],
  researchUnavailable: ["Comparison setup unavailable. Saved runs remain readable.", "آماده‌سازی مقایسه در دسترس نیست. اجراهای ذخیره‌شده همچنان قابل خواندن‌اند."],
  compareError: ["Comparison failed. Check the window, cash, costs and parameter constraints; no order was submitted.", "مقایسه ناموفق بود. بازه، سرمایه، هزینه‌ها و محدودیت پارامترها را بررسی کنید؛ سفارشی ارسال نشده است."],
  comparisonChanged: ["Inputs changed. Run a new matched comparison.", "ورودی‌ها تغییر کردند. مقایسهٔ همسان تازه‌ای اجرا کنید."],
  comparisonLimit: ["Independent paper accounts, not a multi-asset portfolio. Results cannot authorize capital.", "حساب‌های آزمایشی مستقل، نه پرتفوی چنددارایی. نتایج مجوز استفاده از سرمایه نیستند."],
  inspectRun: ["Inspect run", "بررسی اجرا"], parameterFast: ["Fast average bars", "تعداد کندل میانگین سریع"], parameterSlow: ["Slow average bars", "تعداد کندل میانگین کند"],
  parameterRisk: ["Entry risk budget · bps", "بودجهٔ ریسک ورود · واحد پایه"], parameterAllocation: ["Cash allocation cap · bps", "سقف تخصیص وجه · واحد پایه"],
  parameterMaxSpread: ["Maximum entry spread · bps", "حداکثر فاصلهٔ خرید و فروش ورود · واحد پایه"], parameterParticipation: ["Displayed depth participation · bps", "سهم از عمق قابل‌مشاهده · واحد پایه"],
  parameterStopAtr: ["Stop distance · ATR multiple", "فاصلهٔ حد زیان · ضریب ATR"], parameterRewardRisk: ["Target reward / initial risk", "نسبت هدف سود به ریسک اولیه"],
  parameterCooldown: ["Cooldown after exit · bars", "وقفه پس از خروج · کندل"], parameterMaxHolding: ["Maximum holding · bars", "حداکثر نگهداری · کندل"],
  parameterMaxDrawdown: ["Session drawdown lock · bps", "قفل افت سرمایهٔ جلسه · واحد پایه"],
  compoundRiskNote: ["100 bps = 1%. Requires 50 continuous valid closed bars. Wide spreads block entries without resetting valid history or suppressing exits. Stops run at bar close in paper trading; gaps, minimum order sizes and limited depth can exceed the risk budget. These are not exchange stop orders.", "۱۰۰ واحد پایه = ۱٪. به ۵۰ کندل بستهٔ معتبر و پیوسته نیاز دارد. فاصلهٔ زیاد خرید و فروش، ورود را مسدود می‌کند؛ تاریخچهٔ معتبر پاک نمی‌شود و بررسی خروج ادامه دارد. حد زیان در پایان کندل و در معاملهٔ آزمایشی بررسی می‌شود؛ شکاف قیمت، حداقل سفارش و عمق محدود می‌توانند زیان را از بودجه بیشتر کنند. این‌ها سفارش حد زیان صرافی نیستند."],
  parameterLookback: ["Lookback bars", "تعداد کندل گذشته"], parameterEntry: ["Entry distance · bps", "فاصلهٔ ورود · واحد پایه"], parameterConfirmation: ["Closed confirmation bar", "کندل بسته‌شدهٔ تأیید"], parameterReference: ["Reference market", "بازار مرجع"], parameterDeviations: ["Standard deviations", "تعداد انحراف معیار"],
  recentEvidenceEmpty: ["No saved run evidence yet.", "هنوز شواهد اجرای ذخیره‌شده‌ای نیست."],
  researchJobs: ["Scheduled paper research", "پژوهش آزمایشی زمان‌بندی‌شده"], researchAlerts: ["Research alerts", "اعلان‌های پژوهش"],
  runDueResearch: ["Run due jobs now", "اجرای پژوهش‌های سررسیدشده"],
  researchScheduleNote: ["Schedules are stored locally. Continuous execution requires the foreground research runner; this button runs one bounded batch.", "زمان‌بندی‌ها محلی ذخیره می‌شوند. اجرای پیوسته به برنامهٔ پژوهش در حال اجرا نیاز دارد؛ این دکمه یک نوبت محدود را اجرا می‌کند."],
  noResearchJobs: ["No research schedules recorded.", "زمان‌بندی پژوهشی ثبت نشده است."],
  noResearchAlerts: ["No research alerts recorded.", "اعلان پژوهشی ثبت نشده است."],
  nextResearchRun: ["Next due time", "سررسید بعدی"], lastResearchRun: ["Latest result", "آخرین نتیجه"],
  researchRetry: ["Retry at", "زمان تلاش مجدد"], researchPause: ["Pause", "مکث"], researchResume: ["Resume", "ادامه"],
  researchPaused: ["Paused", "متوقف"], researchEnabled: ["Enabled", "فعال"],
  researchControlDone: ["Research control completed. No order was submitted.", "عملیات پژوهشی انجام شد. سفارشی ارسال نشد."],
  researchControlError: ["Research operation failed. Refresh the recorded job state before retrying.", "عملیات پژوهشی ناموفق بود. پیش از تلاش مجدد، وضعیت ثبت‌شده را تازه کنید."],
  researchStateError: ["Research schedules could not be read.", "خواندن زمان‌بندی‌های پژوهش ممکن نیست."],
  RESEARCH_FAILED: ["Paper research failed", "پژوهش آزمایشی ناموفق بود"], RESEARCH_COMPLETED: ["Paper research completed", "پژوهش آزمایشی تکمیل شد"],
  HYPOTHESIS_VERSION_UNAVAILABLE: ["Registered version unavailable · review required", "نسخه ثبت‌شده در دسترس نیست · نیاز به بررسی"],
  REPLAY_VALIDATION_FAILED: ["Paper replay could not complete", "بازپخش آزمایشی تکمیل نشد"],
  COMPLETED: ["Completed", "تکمیل‌شده"], READY: ["Ready", "آماده"], DEGRADED: ["Degraded", "ناقص"],
  MISSING: ["Missing data", "داده موجود نیست"], FUTURE: ["Future timestamp", "زمان در آینده"],
  publicReadiness: ["Public-data readiness", "آمادگی داده‌های عمومی"],
  publicReadinessNote: ["Checks current book sides. A connected stream or fresh ping does not prove fresh quotes or trading authority.", "دو سمت دفتر سفارش اکنون بررسی می‌شوند. اتصال جریان یا پیام تازه، تازگی مظنه یا مجوز معامله را ثابت نمی‌کند."],
  bidAge: ["Bid age · seconds", "سن خرید · ثانیه"], askAge: ["Ask age · seconds", "سن فروش · ثانیه"],
  actions: ["Actions", "عملیات"], FAILED: ["Failed", "ناموفق"], BLOCKED: ["Blocked", "مسدود"],
  validateAction: ["Run chronological validation", "اجرای اعتبارسنجی زمانی"],
  validationWindows: ["Validation windows", "تعداد بازه‌های اعتبارسنجی"],
  validationWindowsHelp: ["Validation only · separate accounts in each window.", "فقط اعتبارسنجی · حساب جداگانه برای هر بازه."],
  validationWindow: ["Window", "بازه"], INCOMPLETE: ["Incomplete evaluation", "ارزیابی ناقص"],
  validationNote: ["Chronological validation selects on the first 70%, skips one decision period, then evaluates the fixed choice on later data. Repeated historical tests are not independent final evidence.", "اعتبارسنجی زمانی با ۷۰٪ نخست انتخاب می‌کند، یک دورهٔ تصمیم را کنار می‌گذارد و انتخاب ثابت را با داده‌های بعدی می‌سنجد. آزمون تاریخی تکراری، شاهد نهایی مستقل نیست."],
  validationTitle: ["Chronological validation", "اعتبارسنجی زمانی"], selectionWindow: ["Selection window", "بازهٔ انتخاب"], holdoutWindow: ["Later evaluation window", "بازهٔ ارزیابی بعدی"],
  selectedCandidate: ["Selected candidate", "گزینهٔ انتخاب‌شده"], ABSTAIN: ["No eligible candidate", "گزینهٔ واجد شرایط وجود ندارد"],
  EVALUATED: ["Evaluated", "ارزیابی‌شده"], STALE_HOLDOUT: ["Later valuation is stale", "ارزش‌گذاری بازهٔ بعدی کهنه است"],
});
Object.assign(vocabulary, {
  sessionKeyTitle: ["Session key", "کلید نشست"], rotateKey: ["Rotate session key", "تعویض کلید نشست"],
  sessionKeyHelp: ["Rotate the key if the private link was shared or saved somewhere. Other tabs and the link printed in the terminal stop working; this tab keeps access.", "اگر پیوند خصوصی جایی هم‌رسانی یا ذخیره شده است، کلید را تعویض کنید. سایر زبانه‌ها و پیوند چاپ‌شده در پایانه از کار می‌افتند و این زبانه دسترسی خود را حفظ می‌کند."],
  rotatedKey: ["New private link for other tabs:", "پیوند خصوصی تازه برای زبانه‌های دیگر:"],
  researchTabs: ["Research sections", "بخش‌های پژوهش"], glossaryTitle: ["What these figures mean", "معنای این ارقام"],
  glossSharpe: ["Sharpe per period · Average return per equity mark divided by its standard deviation. Not annualized for short windows.", "میانگین بازده هر نشانه‌گذاری تقسیم بر انحراف معیار آن. برای بازه‌های کوتاه سالانه نمی‌شود."],
  glossPsr: ["P(true Sharpe > 0) · Probability that the real Sharpe is above zero given this many marks, their skew and fat tails (probabilistic Sharpe ratio).", "احتمال مثبت بودن شارپ واقعی با توجه به تعداد نشانه‌ها، چولگی و دنباله‌های پهن (نسبت شارپ احتمالاتی)."],
  glossDeflated: ["Deflated Sharpe · The same probability, but against the Sharpe the best of all tried configurations would reach by luck.", "همان احتمال، اما در برابر شارپی که بهترینِ همهٔ پیکربندی‌های آزموده‌شده به‌طور شانسی به آن می‌رسد."],
  glossRange: ["90% range · Block bootstrap of the equity returns: nine in ten resampled histories fall inside it. Wide ranges mean little evidence.", "بوت‌استرپ بلوکی بازده‌ها: نه از ده تاریخچهٔ بازنمونه‌گیری در این بازه است. بازهٔ پهن یعنی شواهد کم."],
  glossSortino: ["Sortino · Like Sharpe, but only losses count as risk.", "مانند شارپ، اما فقط زیان‌ها ریسک شمرده می‌شوند."],
  glossCalmar: ["Calmar · Annualized return divided by the maximum drawdown.", "بازده سالانه تقسیم بر بیشترین افت."],
  glossProfitFactor: ["Profit factor · Gross profit of winning trades divided by gross loss of losing trades. Above 1 is profitable before open positions.", "سود ناخالص معاملات برنده تقسیم بر زیان ناخالص معاملات بازنده. بالاتر از ۱ یعنی سودآور، بدون موقعیت باز."],
  glossExposure: ["Time in market · Share of the window with a position open.", "سهم زمانی از بازه که موقعیتی باز بوده است."],
  glossTurnover: ["Turnover · Value of all fills divided by starting cash. Costs grow with it.", "ارزش همهٔ معاملات تقسیم بر سرمایهٔ اولیه. هزینه‌ها با آن بزرگ می‌شوند."],
  glossKelly: ["Kelly fraction · Share of cash the win rate and payoff would justify, if they held. Real use is a fraction of it; shown after 20 trades.", "سهمی از نقد که نرخ برد و نسبت سود به زیان توجیه می‌کند، اگر پایدار بمانند. در عمل کسری از آن؛ پس از ۲۰ معامله."],
  glossBeta: ["Beta, alpha, information ratio · Against simply holding the base asset over the same marks: beta is sensitivity, alpha the return left over, information ratio that excess per unit of tracking error.", "در برابر نگهداری دارایی پایه در همان نشانه‌ها: بتا حساسیت، آلفا بازده باقی‌مانده و نسبت اطلاعات آن مازاد به‌ازای خطای ردیابی است."],
  glossAvgCost: ["Average cost · Realized profit if each sale used the average purchase price instead of the oldest lots first.", "سود تحقق‌یافته اگر هر فروش به‌جای قدیمی‌ترین خریدها، میانگین قیمت خرید را مبنا بگیرد."],
  chartKeys: ["Arrow keys step through the marks", "کلیدهای جهت‌نما نشانه‌ها را مرور می‌کنند"], underwater: ["Below the running peak", "زیر بالاترین سطح تا آن لحظه"],
  overlayTitle: ["Equity paths · return from start", "مسیر ارزش حساب · بازده از آغاز"], pickRun: ["Select for comparison", "انتخاب برای مقایسه"],
  comparePicked: ["Compare selected", "مقایسهٔ انتخاب‌شده‌ها"], savedComparisonTitle: ["Saved runs side by side", "اجراهای ذخیره‌شده کنار هم"],
  savedComparisonNote: ["Runs can differ in window, market, cash and costs; this view does not make them a matched comparison.", "اجراها ممکن است در بازه، بازار، سرمایه و هزینه متفاوت باشند؛ این نما آن‌ها را مقایسهٔ هم‌شرایط نمی‌کند."],
  downloadCsv: ["Download CSV", "دریافت CSV"], window: ["Window", "بازه"],
  alertsOn: ["Desktop alerts: on", "هشدار دسکتاپ: روشن"], alertsOff: ["Desktop alerts: off", "هشدار دسکتاپ: خاموش"],
  alertDisk: ["Less than a day of disk left before collection stops.", "کمتر از یک روز تا توقف گردآوری به‌دلیل کمبود فضا باقی است."],
  alertStall: ["No market data for over two minutes.", "بیش از دو دقیقه دادهٔ بازار دریافت نشده است."],
  alertClock: ["The system clock went backward; publication is paused.", "ساعت سیستم به عقب برگشته است؛ انتشار متوقف است."],
  alertIntegrity: ["A raw archive file no longer matches its recorded hash.", "یک فایل بایگانی خام با درهم‌سازی ثبت‌شده مطابقت ندارد."],
  poorData: ["Poor data", "دادهٔ ضعیف"], storageTitle: ["Storage and feed", "ذخیره‌سازی و خوراک داده"], freeSpace: ["Free space", "فضای آزاد"],
  stopFloor: ["Collection stops below", "توقف گردآوری زیر"], growthPerHour: ["Raw archive growth per hour", "رشد بایگانی خام در ساعت"],
  hoursToFloor: ["Hours until the floor", "ساعت تا رسیدن به کف"], lastArchive: ["Last automatic archive · days moved", "آخرین بایگانی خودکار · روزهای منتقل‌شده"],
  integritySweep: ["Last integrity sweep", "آخرین بررسی یکپارچگی"], shard: ["Connection", "اتصال"], markets: ["Markets", "بازارها"],
  noShards: ["No live connections yet.", "هنوز اتصال زنده‌ای وجود ندارد."],
  executionModel: ["Execution and sizing · optional", "اجرا و اندازهٔ موقعیت · اختیاری"], orderType: ["Order type", "نوع سفارش"],
  orderMarket: ["Market · cross the spread", "بازار · عبور از اختلاف قیمت"], orderLimit: ["Limit · rest at the near touch", "محدود · انتظار در بهترین قیمت"],
  makerFee: ["Maker fee · limit fills", "کارمزد سفارش‌گذار · سفارش محدود"], maxFraction: ["Max share of cash per entry", "سقف سهم نقد در هر ورود"],
  volTarget: ["Target volatility per bar", "نوسان هدف در هر میله"], walkDepth: ["Fill across stored book levels", "اجرا در چند سطح دفتر سفارش"],
  carryRemainder: ["Keep working a resized order", "ادامهٔ اجرای باقی‌ماندهٔ سفارش"],
  executionHelp: ["Limit orders fill only when later trades clear the queue ahead or the market trades through. Book levels need a collector started with --depth-levels. Volatility targeting buys nothing until 20 decision bars exist.", "سفارش محدود فقط وقتی اجرا می‌شود که معاملات بعدی صف جلویی را تمام کنند یا قیمت از آن عبور کند. سطوح دفتر سفارش به گردآوری با --depth-levels نیاز دارد. هدف‌گذاری نوسان تا ۲۰ میلهٔ تصمیم چیزی نمی‌خرد."],
  sharpeRange: ["Sharpe per period · 90% range", "شارپ هر دوره · بازهٔ ۹۰٪"], returnRange: ["Total return · 90% range", "بازده کل · بازهٔ ۹۰٪"],
  beta: ["Beta against", "بتا نسبت به"], alphaPeriod: ["Alpha per period", "آلفای هر دوره"], infoRatio: ["Information ratio per period", "نسبت اطلاعات هر دوره"],
  correlation: ["Correlation", "همبستگی"], avgCostPnl: ["Realized P/L · average cost", "سود/زیان تحقق‌یافته · میانگین بها"], tabRuns: ["Saved runs", "اجراهای ذخیره‌شده"], tabCompare: ["Compare", "مقایسه"],
  tabSchedules: ["Schedules", "زمان‌بندی‌ها"], tabMargin: ["Margin", "تعهدی"], tabWorkbench: ["Workbench", "کارگاه"],
  startCompare: ["Compare two strategies", "مقایسهٔ دو راهبرد"],
  perfTitle: ["Risk and return", "ریسک و بازده"], totalReturn: ["Total return", "بازده کل"], maxDrawdown: ["Max drawdown", "بیشترین افت"],
  sharpePeriod: ["Sharpe · per period", "شارپ · هر دوره"], psr: ["P(true Sharpe > 0)", "احتمال شارپ واقعی بیش از صفر"],
  winRate: ["Win rate", "نرخ برد"], closedTrades: ["closed trades", "معاملهٔ بسته‌شده"],
  annualReturn: ["Annualized return", "بازده سالانه"], needs30: ["Needs a 30-day window", "نیازمند بازهٔ ۳۰ روزه"],
  volatility: ["Volatility per period", "نوسان هر دوره"], sortino: ["Sortino · annualized", "سورتینو · سالانه"], calmar: ["Calmar ratio", "نسبت کالمار"],
  profitFactor: ["Profit factor", "ضریب سود"], expectancy: ["Expectancy per trade", "میانگین سود هر معامله"],
  avgWin: ["Average win", "میانگین برد"], avgLoss: ["Average loss", "میانگین باخت"], avgHolding: ["Average holding · hours", "میانگین نگهداری · ساعت"],
  losingStreak: ["Longest losing streak", "طولانی‌ترین زنجیرهٔ زیان"], turnover: ["Turnover · × starting cash", "گردش · برابر سرمایهٔ اولیه"],
  exposure: ["Time in market", "زمان حضور در بازار"], kelly: ["Kelly fraction · full, not advice", "کسر کلی · کامل، توصیه نیست"],
  openPosition: ["Open position · base", "موقعیت باز · دارایی پایه"],
  perfNote: ["Per-period figures use the equity marks. Annualized figures appear only for windows of 30 days or more. P(true Sharpe > 0) is the probabilistic Sharpe ratio, which allows for skew and fat tails.", "ارقام هر دوره از نشانه‌گذاری ارزش حساب محاسبه می‌شوند. ارقام سالانه فقط برای بازه‌های ۳۰ روزه یا بیشتر نمایش داده می‌شوند. احتمال شارپ واقعی بیش از صفر، نسبت شارپ احتمالاتی است و چولگی و دنباله‌های پهن را در نظر می‌گیرد."],
  tradesTitle: ["Closed trades · first in, first out", "معاملات بسته‌شده · اولین ورود، اولین خروج"],
  opened: ["Opened", "باز شدن"], closed: ["Closed", "بسته شدن"], holding: ["Hours", "ساعت"], cost: ["Cost", "بهای تمام‌شده"],
  proceeds: ["Proceeds", "عایدی"], pnl: ["Profit / loss", "سود / زیان"], tradeReturn: ["Return", "بازده"],
  noTrades: ["No closed trades in this run.", "در این اجرا معاملهٔ بسته‌شده‌ای وجود ندارد."],
  showMore: ["Show more", "نمایش بیشتر"], decisionLog: ["Decision log · JSON", "گزارش تصمیمات · JSON"], decisionAction: ["Action", "اقدام"], reasons: ["Reasons", "دلایل"],
  selectionTitle: ["Selection check · deflated Sharpe", "آزمون انتخاب · شارپ تعدیل‌شده"],
  selectionNote: ["Choosing the best of several candidates on the same data inflates its Sharpe. The deflated Sharpe is the probability that the winner's true Sharpe beats what luck alone gives the best of this many trials.", "انتخاب بهترین گزینه از میان چند گزینه روی یک داده، شارپ آن را بزرگ‌تر نشان می‌دهد. شارپ تعدیل‌شده احتمال این است که شارپ واقعی برنده از آنچه شانس به بهترینِ این تعداد آزمون می‌دهد بیشتر باشد."],
  trials: ["Trials", "تعداد آزمون"], bestCandidate: ["Best candidate", "بهترین گزینه"], luckThreshold: ["Luck threshold · Sharpe per period", "آستانهٔ شانس · شارپ هر دوره"],
  deflatedSharpe: ["Deflated Sharpe", "شارپ تعدیل‌شده"],
  participation: ["Max share of displayed size · optional", "سقف سهم از حجم نمایش‌داده‌شده · اختیاری"],
  participationHelp: ["Fraction of the best-level quantity one fill may take, for example 0.25. Leave empty for no cap.", "سهمی از حجم بهترین سطح که یک معامله می‌تواند بردارد، برای مثال 0.25. برای بدون سقف خالی بگذارید."],
  latestNet: ["Latest paper result", "آخرین نتیجهٔ آزمایشی"], latestNetNote: ["Net of fees and spread", "پس از کارمزد و اختلاف قیمت"],
  exactValues: ["Exact values", "مقادیر دقیق"],
  catalogSource: ["Catalogue source", "منبع فهرست بازار"],
  RETAINED_METADATA: ["Retained metadata · current catalogue freshness unknown", "فرادادهٔ ذخیره‌شده · تازگی فهرست فعلی نامعلوم"],
  PUBLIC_REST: ["Public REST receipt", "دریافت عمومی REST"],
  period: ["Indicator period · bars", "دوره شاخص · شمع"],
  entry_threshold: ["Entry threshold", "آستانه ورود"], exit_threshold: ["Exit threshold", "آستانه خروج"],
  signal: ["Signal period · bars", "دوره سیگنال · شمع"], ema_period: ["EMA period · bars", "دوره میانگین نمایی · شمع"],
  range_period: ["Range period · bars", "دوره دامنه · شمع"], multiplier: ["Band multiplier", "ضریب باند"],
  adx_threshold: ["Minimum ADX", "کمینه ADX"],
  exit_lookback: ["Exit channel · bars", "کانال خروج · شمع"],
  compression_bps: ["Maximum prior width · bps · 0 disables", "بیشینه پهنای قبلی · واحد پایه · صفر غیرفعال"],
  regime: ["Entry regime gate", "فیلتر رژیم ورود"],
  regime_gate: ["Shared entry regime gate", "فیلتر مشترک رژیم ورود"],
  sortMarkets: ["Sort markets", "مرتب‌سازی بازارها"],
  overlayInspectionNote: ["Each series starts at its first recorded equity mark. Cursor values require an exact recorded time; missing samples are unavailable, not interpolated.", "آغاز هر سری نخستین ارزش ثبت‌شده آن است. مقدار نشانگر به زمان دقیق ثبت نیاز دارد؛ نمونه مفقود درون‌یابی نمی‌شود."],
  sharedStrategyControls: ["Optional regime and exit controls", "کنترل‌های اختیاری رژیم و خروج"],
  sharedStrategyControlsNote: ["Default off. Closed-bar paper exits use actual fills; gaps, costs and closures can exceed thresholds. No venue protection is placed.", "پیش‌فرض خاموش است. خروج آزمایشی در پایان کندل از اجراهای واقعی مدل استفاده می‌کند؛ شکاف، هزینه و تعطیلی می‌تواند از حد عبور کند. حفاظتی در صرافی ثبت نمی‌شود."],
  sortSpread: ["Spread · lowest first", "فاصله قیمت · کمترین ابتدا"],
  sortAge: ["Quote age · oldest first", "عمر قیمت · قدیمی‌ترین ابتدا"],
  creditRatioGrid: ["Credit ratio · min → max · step", "نسبت اعتبار · کمینه تا بیشینه · گام"],
  marginDirections: ["Margin directions", "جهت‌های تعهدی"],
  sampleReady: ["Ready runs · newest sample", "اجراهای آماده · نمونه اخیر"],
  sampleTraded: ["Traded runs · newest sample", "اجراهای دارای معامله · نمونه اخیر"],
  sampleUnavailable: ["Unverifiable runs · newest sample", "اجراهای غیرقابل بررسی · نمونه اخیر"],
  exit_stop_bps: ["Fixed exit loss · bps · 0 off", "حد زیان خروج · واحد پایه · صفر خاموش"],
  exit_profit_bps: ["Profit exit · bps · 0 off", "حد سود خروج · واحد پایه · صفر خاموش"],
  exit_atr_multiple: ["Trailing exit · ATR multiple · 0 off", "خروج متحرک · ضریب ATR · صفر خاموش"],
  exit_after_bars: ["Maximum holding · bars · 0 off", "بیشینه نگهداری · کندل · صفر خاموش"],
  marketProducts: ["Buy, sell, margin and credit scope", "دامنه خرید، فروش، تعهدی و اعتبار"],
  productScopeHelp: ["Read all observed markets. Margin grids require a saved current public catalogue; trade credit requires separate account eligibility.", "همه بازارهای مشاهده‌شده خوانده می‌شوند. گام اعتبار به فهرست عمومی تازه و اعتبار معاملاتی به احراز شرایط جداگانه حساب نیاز دارد."],
  loadProducts: ["Inspect observed products", "بررسی محصولات مشاهده‌شده"],
  loadMarginProducts: ["Open margin rules and preview", "قواعد و پیش‌نمایش تعهدی"],
  campaignProgress: ["Study progress", "پیشرفت مطالعه"],
  loadProgress: ["Inspect progress and verified results", "بررسی پیشرفت و نتایج"],
  definedExperiments: ["Defined experiments", "آزمایش‌های تعریف‌شده"],
  registeredAttempts: ["Registered attempts", "تلاش‌های ثبت‌شده"],
  unreportedAttempts: ["Attempts without a terminal result", "تلاش‌های بدون نتیجه نهایی"],
  usdtValuation: ["USDT equivalent · valuation only", "معادل تتر · فقط ارزش‌گذاری"],
  fxState: ["FX status", "وضعیت تبدیل"],
  fxAge: ["Rate age · seconds", "عمر نرخ · ثانیه"],
  fxCurveNote: ["Latest 25 marks. Old rates remain STALE or STALE_CLOSED. Missing rates stay unavailable and prevent a joined curve. Conversion cannot make stale holdings current or certify an executable price.", "۲۵ ارزش‌گذاری آخر؛ نرخ قدیمی STALE یا STALE_CLOSED می‌ماند. نرخ ناموجود خالی است و نمودار پیوسته رسم نمی‌شود. تبدیل، دارایی کهنه را تازه نمی‌کند و قیمت قابل‌اجرا را تأیید نمی‌کند."],
});
const T = Object.fromEntries(["en", "fa"].map((language, i) => [language,
  Object.fromEntries(Object.entries(vocabulary).map(([key, values]) => [key, values[i]]))]));
const $ = id => document.getElementById(id);
function saved(key, fallback, allowed) {
  try { const value = localStorage.getItem(key); return allowed.includes(value) ? value : fallback; }
  catch (_) { return fallback; }
}
function remember(key, value) { try { localStorage.setItem(key, value); } catch (_) { /* Storage is optional. */ } }
let lang = saved("lang", "en", ["en", "fa"]);
let theme = saved("theme", "light", ["light", "dark"]);
const state = { view: "overview", markets: null, quote: "", filter: "", expanded: "", runs: [], runCount: 50, runFilter: "", pickedRuns: new Set(), overlays: new Map(),
  selectedRun: "", record: null, health: null, rules: null, apiError: false, savingRules: false,
  researchSetup: null, researchState: null, researchBusy: false, comparison: null, comparing: false, candidateParams: {} };
let comparisonRevision = 0;
const t = key => T[lang][key] ?? key;
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const digits = value => lang === "fa" ? String(value).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]) : String(value);
// Keep API money as decimal strings; floating point is used only for chart geometry.
function num(value) {
  if (value == null || value === "") return t("none");
  const raw = String(value), match = raw.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return esc(raw);
  return digits(match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (match[3] ? "." + match[3] : ""));
}
function when(value, dateOnly = false, timeZone = "Asia/Tehran") {
  if (!value) return t("none");
  const stamp = new Date(value);
  if (!Number.isFinite(stamp.getTime())) return t("unknown");
  return new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", {
    timeZone, year: "numeric", month: "short", day: "numeric",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit" }),
  }).format(stamp);
}
// Round a decimal string half-up for display only; the exact value stays in the tooltip.
function rounded(value, places = 2) {
  const match = String(value ?? "").match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match || (match[3] || "").length <= places) return value;
  const [, sign, whole, fraction] = match;
  let scaled = whole + fraction.slice(0, places);
  if (fraction[places] >= "5") scaled = (BigInt(scaled) + 1n).toString().padStart(scaled.length, "0");
  const text = places ? `${scaled.slice(0, -places) || "0"}.${scaled.slice(-places)}` : scaled;
  return /^[0.]*$/.test(text) ? text : sign + text;
}
// U+2066/U+2069 isolate a signed figure left-to-right in Persian text, and survive HTML escaping.
const ratio = (value, places = 2) => value == null || !Number.isFinite(Number(value)) ? t("none") : `\u2066${digits(Number(value).toFixed(places))}\u2069`;
const percent = (value, places = 1) => value == null || !Number.isFinite(Number(value)) ? t("none") : `\u2066${digits((Number(value) * 100).toFixed(places))} %\u2069`;
const signed = value => String(value ?? "").startsWith("-") ? "neg" : Number(value) > 0 ? "pos" : "";
const list = value => Array.isArray(value) ? value : [];
const code = value => `<bdi dir="ltr">${esc(value ?? t("none"))}</bdi>`;
const amount = value => `<bdi dir="ltr">${num(value)}</bdi>`;
const money = (value, places = 2) => value == null || value === "" ? esc(t("none")) : `<bdi dir="ltr" title="${esc(num(value))}">${num(rounded(value, places))}</bdi>`;
const label = value => esc(t(String(value ?? "unknown")));
const chip = (text, kind = "warn") => `<span class="chip chip-${kind}">${esc(text)}</span>`;
const empty = (title, help = "") => `<div class="empty-state"><p class="empty-title">${esc(title)}</p>${help ? `<p class="field-help">${esc(help)}</p>` : ""}</div>`;
const json = value => `<pre class="output mono" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
const disclosure = (title, value, key) => `<details class="disclosure" data-key="${esc(key)}"><summary>${esc(title)}</summary>${json(value)}</details>`;
const stat = (name, value, note = "") => `<div class="stat"><span class="stat-label">${esc(name)}</span><strong class="stat-value">${value}</strong>${note ? `<span class="stat-note">${esc(note)}</span>` : ""}</div>`;
const keyValues = rows => `<dl class="key-values">${rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
// `numeric` lists column indexes that hold numbers: right-aligned, tabular figures.
function table(headings, rows, fallback, numeric = []) {
  if (!rows.length) return empty(fallback || t("nothing"));
  const cls = i => numeric.includes(i) ? ' class="num"' : "";
  return `<div class="table-wrap" tabindex="0"><table class="data"><thead><tr>${headings.map((h, i) => `<th scope="col"${cls(i)}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map((cell, i) => `<td${cls(i)} data-label="${esc(headings[i] ?? "")}">${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const rendered = new Map();
function setHTML(id, html) {
  const element = $(id);
  if (rendered.get(id) === html) return;
  const open = new Set([...element.querySelectorAll("details[data-key]")].filter(detail => detail.open).map(detail => detail.dataset.key));
  const focus = document.activeElement?.dataset?.focus;
  const focusedInside = focus && [...element.querySelectorAll("[data-focus]")].includes(document.activeElement);
  element.innerHTML = html;
  rendered.set(id, html);
  for (const detail of element.querySelectorAll("details[data-key]")) detail.open = open.has(detail.dataset.key);
  if (focusedInside) [...element.querySelectorAll("[data-focus]")].find(node => node.dataset.focus === focus)?.focus({ preventScroll: true });
}

async function api(path, options = {}, timeoutMs = 10000, asText = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { ...options, cache: "no-store", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-Gym-Token": TOKEN, ...options.headers } });
    if (!response.ok) {
      // Kept off the page by default: some server errors quote submitted material. Callers with non-secret forms opt in.
      const error = new Error(t("requestError"));
      if (response.status < 500) error.detail = await response.json().then(body => typeof body?.error === "string" ? body.error.slice(0, 240) : "", () => "");
      throw error;
    }
    return asText ? await response.text() : await response.json();
  } catch (error) {
    throw Object.assign(new Error(t("requestError")), { detail: error.detail || "" });
  } finally { clearTimeout(timeout); }
}

function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  document.documentElement.setAttribute("data-theme", theme);
  document.title = t("title");
  document.querySelectorAll("[data-t]").forEach(element => { element.textContent = t(element.dataset.t); });
  document.querySelectorAll("[data-t-placeholder]").forEach(element => { element.setAttribute("placeholder", t(element.dataset.tPlaceholder)); });
  document.querySelectorAll("[data-t-label]").forEach(element => { element.setAttribute("aria-label", t(element.dataset.tLabel)); });
  $("language-toggle").textContent = lang === "fa" ? "English" : "فارسی";
  $("language-toggle").setAttribute("lang", lang === "fa" ? "en" : "fa");
  $("theme-toggle").textContent = t(theme === "light" ? "darkTheme" : "lightTheme");
  $("current-view").textContent = t(viewKeys[state.view]);
  renderMarkets(); renderRunList();
  if (state.record) renderRun(state.record);
  else if (state.savedComparison) renderSavedComparison(state.savedComparison);
  if (state.health) renderHealth(state.health);
  if (state.rules) renderRules(state.rules);
  renderOverview(); renderTicketFields(); renderFeed(); updateClock();
  if (state.researchSetup) { for (const slot of ["first", "second"]) renderCandidate(slot); renderCoverage(); }
  renderComparison();
  if (state.researchState) renderResearchJobs(state.researchState);
  if (state.view === "models") window.gymModels?.mount(api, esc);
  if (state.view === "research") { window.gymResearch?.mount(api, esc); window.gymMargin?.mount({api, esc, keyValues, table, amount, when, demo: DEMO}); window.gymPortfolio?.mount({api, esc, table, keyValues, amount, when, curveFigure, strategyFields}); }
}

function renderOverview() {
  const markets = list(state.markets?.markets), latest = state.runs[0];
  setHTML("overview-summary", stat(t("observedPairs"), state.markets ? num(markets.length) : t("none"), t("observedPairsNote"))
    + stat(t("healthyQuotes"), state.markets ? num(markets.filter(healthyQuote).length) : t("none"), t("healthyQuotesNote"))
    + stat(t("savedRunCount"), state.runsLoaded ? num(state.runs.length) : t("none"), t("runCountNote"))
    + stat(t("latestNet"), latest?.end ? `<span class="${signed(latest.end.net)}">${money(latest.end.net)}</span> <small>${esc(/(TMN|USDT)$/.exec(latest.inputs?.symbol || "")?.[1] || "")}</small>` : esc(t("none")), t("latestNetNote")));
  setHTML("overview-markets", state.markets ? table([t("pair"), t("bid"), t("ask"), t("spreadBps"), t("entry")], markets.slice(0, 5).map(m => [code(m.symbol), amount(m.bid), amount(m.ask), amount(m.spread_bps), eligibility(m.act?.entry)]), t("noMarkets"), [1, 2, 3]) : empty(t("loading")));
  const record = state.record, result = record?.result;
  setHTML("overview-research", result ? `<div class="run-heading"><h3>${code(result.symbol)} <span class="muted">${esc(result.strategy || "")}</span></h3>${chip(t(record.inputs?.store === "demo" ? "synthetic" : "paperOnly"))}</div>${curveFigure(result)}${keyValues([[t("net"), `${money(result.end?.net)} ${code(result.quote)}`], [t("totalReturn"), pct(record.evidence?.performance?.total_return_pct)], [t("fills"), num(result.fills)]])}<p class="field-help">${esc(record.evidence?.primary_limitation || t("noCapital"))}</p>` : empty(t(state.runsLoaded ? "noRuns" : "loading"), t("noRunsHelp")));
  setHTML("overview-activity", state.runs.length ? table([t("pair"), t("time"), t("net")], state.runs.slice(0, 4).map(run => [code(run.inputs?.symbol), esc(when(run.inputs?.to)), `${money(run.end?.net)} ${code(/(TMN|USDT)$/.exec(run.inputs?.symbol || "")?.[1])}`]), "", [2]) : empty(t(state.runsLoaded ? "recentEvidenceEmpty" : "loading")));
}

function renderFeed() {
  const health = state.health;
  const key = state.apiError ? "refreshFailed" : !health ? "feedUnknown" : health.fatal ? "feedStopped" : health.connected ? "feedConnected" : "feedDisconnected";
  const readiness = health?.readiness;
  const ready = list(readiness?.markets).filter(row => row.state === "READY").length;
  setHTML("feed-status", `<span class="dot${state.apiError || health?.fatal || !health?.connected || readiness?.ready !== true ? " dot-warn" : ""}" aria-hidden="true"></span><span>${esc(t(key))}${readiness ? ` · ${esc(t("publicReadiness"))}: ${label(readiness.status)} · ${digits(ready)}/${digits(list(readiness.markets).length)}` : ""}</span>`);
  $("connection-error").hidden = !state.apiError;
}
function updateClock() {
  const now = new Date();
  $("clock").textContent = new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", { timeZone: "Asia/Tehran", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(now) + " · " + (lang === "fa" ? "تهران" : "Tehran");
  $("clock").setAttribute("datetime", now.toISOString());
}
let pollTimer, refreshTask, refreshAgain = false;
async function collectView(name, healthTask) {
  if (name === "operate") window.gymNativeReview?.mount(api, DEMO);
  if (name === "backups") {
    try {
      const value = await api("/api/backup-status");
      setHTML("backup-operation-status", `<p>${code(value.state)}</p><p>${esc(t("backupReceiptScope"))}</p>` + (value.state === 'NO_RECEIPTS'
        ? `<p>${esc(t("noBackupReceipts"))}</p>` : Object.entries(value.latest ?? {}).filter(([, row]) => row).map(([kind, row]) =>
          `<article><h3>${esc(t(kind === 'BACKUP' ? 'backupWorkflow' : 'restoreWorkflow'))}</h3><p>${esc(when(row.recorded_at))}</p><pre class="output" dir="ltr">${esc(JSON.stringify(row, null, 2))}</pre></article>`).join('')));
    } catch (error) { setHTML("backup-operation-status", `<p>${esc(t("requestError"))}</p>`); throw error; }
  }
  if (name === "models") await window.gymModels?.mount(api, esc);
  if (name === "overview") {
    const results = await Promise.allSettled([
      api("/api/markets").then(data => { state.markets = data; renderMarkets(); }),
      research().then(() => { state.runsLoaded = true; }), operate(),
    ]);
    renderOverview();
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "markets") { state.markets = await api("/api/markets"); renderMarkets(); }
  if (name === "research") {
    window.gymResearch?.mount(api, esc);
    window.gymMargin?.mount({api, esc, keyValues, table, amount, when, demo: DEMO}); window.gymPortfolio?.mount({api, esc, table, keyValues, amount, when, curveFigure, strategyFields});
    const results = await Promise.allSettled([research(), researchJobs()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "account") {
    const results = await Promise.allSettled([accountJournal(), externalJournal(), offlineReviews()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
  if (name === "operate" || name === "safety") await operate();
  if (name === "rules") await rules();
  if (name === "health") {
    const results = await Promise.allSettled([healthTask.then(renderHealth), venueFacts(), chaos()]);
    if (results.some(result => result.status === "rejected")) throw new Error(t("requestError"));
  }
}
// Desktop notifications for conditions that need the operator, once per condition until it clears.
let alertsOn = saved("alerts", "off", ["on", "off"]) === "on";
const alerted = new Set();
function checkAlerts(health) {
  if (!alertsOn || typeof Notification === "undefined" || Notification.permission !== "granted" || !health) return;
  const active = [
    ...(health.storage?.hours_to_floor != null && health.storage.hours_to_floor < 24 ? [["disk", t("alertDisk")]] : []),
    ...(health.connected && health.last_frame_age_s > 120 ? [["stall", t("alertStall")]] : []),
    ...(health.clock_paused ? [["clock", t("alertClock")]] : []),
    ...(health.integrity?.mismatched ? [["integrity", t("alertIntegrity")]] : []),
    ...(health.fatal ? [["fatal", String(health.fatal)]] : []),
  ];
  for (const [key, body] of active) if (!alerted.has(key)) { alerted.add(key); new Notification("TradingGYM", { body, tag: key }); }
  for (const key of [...alerted]) if (!active.some(([name]) => name === key)) alerted.delete(key);
}
function renderAlertToggle() {
  $("alerts-toggle").textContent = t(alertsOn ? "alertsOn" : "alertsOff");
  $("alerts-toggle").setAttribute("aria-pressed", String(alertsOn));
}
$("alerts-toggle").addEventListener("click", async () => {
  if (!alertsOn && typeof Notification !== "undefined" && Notification.permission !== "granted") await Notification.requestPermission();
  alertsOn = !alertsOn && typeof Notification !== "undefined" && Notification.permission === "granted";
  remember("alerts", alertsOn ? "on" : "off"); renderAlertToggle();
});
renderAlertToggle();
// The page stops refreshing while hidden; alerts still need a slow health check.
setInterval(() => { if (document.hidden && alertsOn) api("/api/health").then(checkAlerts, () => {}); }, 60000);
async function refresh() {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  if (refreshTask) { refreshAgain = true; return refreshTask; }
  const name = state.view;
  updateClock();
  refreshTask = (async () => {
    const healthTask = api("/api/health").then(data => { state.health = data; checkAlerts(data); return data; });
    const results = await Promise.allSettled([healthTask, collectView(name, healthTask)]);
    if (state.view === name) state.apiError = results.some(result => result.status === "rejected");
    renderFeed();
  })();
  try { await refreshTask; }
  finally {
    refreshTask = null;
    const again = refreshAgain; refreshAgain = false;
    if (!document.hidden) pollTimer = setTimeout(refresh, again ? 0 : 2000);
  }
}
const viewKeys = { overview: "navOverview", markets: "navMarkets", research: "navResearch", account: "navAccount", operate: "navOperate", rules: "navRules", health: "navHealth", safety: "navSafety", backups: "navBackups", models: "navModels" };
async function showView(name, focus = false) {
  if (!Object.hasOwn(viewKeys, name)) name = "overview";
  state.view = name;
  document.querySelectorAll("[data-view]").forEach(link => {
    if (link.dataset.view === name) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  Object.keys(viewKeys).forEach(view => { $("v-" + view).hidden = view !== name; });
  $("current-view").textContent = t(viewKeys[name]);
  if (focus) $("main").focus({ preventScroll: false });
  return refresh();
}

$("market-filter").addEventListener("input", event => { state.filter = event.target.value; renderMarkets(); });
for (const id of ['market-quality', 'market-sort']) $(id).addEventListener('change', renderMarkets);
$("products-refresh").onclick = async event => {
  const button = event.target; button.disabled = true;
  setHTML("product-capabilities", empty(t("loading")));
  try {
    const report = await api('/api/research/action', {method: 'POST', body: JSON.stringify({action: 'market-products', value: {margin_catalogue_id: window.gymMargin?.catalogueId() || null}})}, 130000);
    setHTML("product-capabilities", `<p class="field-help">${esc(report.scope)} · ${esc(when(report.as_of))}</p>${table([t("pair"), t("entry"), t("exit"), t("status"), t("creditRatioGrid"), t("marginDirections"), t("funded_authority")], list(report.markets).map(row => [code(row.symbol), code(row.spot.buy), code(row.spot.sell), code(row.margin.status), row.margin.credit_grid ? `${code(row.margin.credit_grid.minimum)} → ${code(row.margin.credit_grid.maximum)} · ${code(row.margin.credit_grid.step)}` : code(row.trade_credit), list(row.margin.directions).map(code).join(' / '), code(row.funded_submission)]))}`);
  } catch (_) { setHTML("product-capabilities", empty(t("requestError"))); }
  finally { button.disabled = false; }
};
$("products-margin").onclick = async () => { await showView('research'); showResearchTab('margin', true); };
$("campaign-refresh").onclick = async event => {
  const button = event.target; button.disabled = true;
  setHTML('campaign-progress', empty(t('loading')));
  try {
    const report = await api('/api/research/action', {method:'POST', body:JSON.stringify({action:'campaign-status', value:{limit:25}})}, 130000);
    setHTML('campaign-progress', keyValues([[t('definedExperiments'), num(report.defined_experiments)], [t('registeredAttempts'), num(report.registered_attempts)], [t('COMPLETED'), num(report.completed)], [t('unreportedAttempts'), num(report.unreported_attempts)], [t('sampleReady'), num(report.verified_sample?.ready_runs)], [t('sampleTraded'), num(report.verified_sample?.traded_runs)], [t('sampleUnavailable'), num(report.verified_sample?.unavailable_runs)], [t('updated'), esc(when(report.last_recorded_progress))]]) + `<p class="field-help">${esc(report.scope)}</p>${table([t('status'), t('runs')], Object.entries(report.terminal_states).map(([key, count]) => [label(key), num(count)]))}${table([t('pair'), t('strategy'), t('status'), t('ready'), t('fills'), t('net'), t('reason')], list(report.verified_sample?.rows).map(row => [code(row.symbol), code(row.strategy), code(row.verification || row.state), row.ready == null ? label('UNKNOWN') : label(row.ready ? 'READY' : 'NOT_READY'), num(row.fills), `${money(row.net_quote)} ${code(row.quote)}`, esc(row.reason || '')]))}`);
  } catch (_) { setHTML('campaign-progress', empty(t('requestError'))); }
  finally { button.disabled = false; }
};
$("quote-filter").addEventListener("click", event => {
  const button = event.target.closest?.("[data-quote]") || event.target;
  if (button.dataset.quote !== undefined) { state.quote = button.dataset.quote; renderMarkets(); }
});
$("market-rows").addEventListener("click", event => {
  const button = event.target.closest?.("[data-market]") || event.target;
  if (!button.dataset.market) return;
  state.expanded = state.expanded === button.dataset.market ? "" : button.dataset.market;
  renderMarkets();
});
const researchTabs = ["runs", "compare", "schedules", "margin", "workbench"];
let researchTab = saved("researchTab", "runs", researchTabs);
function showResearchTab(name, focus = false, link = true) {
  if (name !== researchTab) window.scrollTo?.({ top: 0 });
  researchTab = name; remember("researchTab", name);
  document.querySelectorAll("#research-tabs [role=tab]").forEach(tab => {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(on)); tab.tabIndex = on ? 0 : -1;
    if (on && focus) tab.focus();
  });
  for (const tab of researchTabs) $("panel-" + tab).hidden = tab !== name;
  if (link) linkResearch();
}
$("research-tabs").addEventListener("click", event => {
  const tab = event.target.closest?.("[data-tab]") || event.target;
  if (tab.dataset.tab) showResearchTab(tab.dataset.tab);
});
$("research-tabs").addEventListener("keydown", event => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key] * (document.documentElement.dir === "rtl" ? -1 : 1);
  const index = event.key === "Home" ? 0 : event.key === "End" ? researchTabs.length - 1
    : step ? (researchTabs.indexOf(researchTab) + step + researchTabs.length) % researchTabs.length : -1;
  if (index < 0) return;
  event.preventDefault(); showResearchTab(researchTabs[index], true);
});
showResearchTab(researchTab);
function selectSavedRun(event) {
  const button = event.target.closest?.("[data-run]") || event.target;
  if (!button.dataset.run) return;
  state.selectedRun = button.dataset.run; state.record = null; state.savedComparison = false;
  showResearchTab("runs"); renderRunList(); refresh();
}
$("run-list").addEventListener("click", selectSavedRun);
$("run-list").addEventListener("change", event => {
  const id = event.target.dataset?.pick;
  if (!id) return;
  if (event.target.checked && state.pickedRuns.size < 4) state.pickedRuns.add(id); else { state.pickedRuns.delete(id); event.target.checked = false; }
  renderRunList();
});
$("compare-picked").addEventListener("click", async () => {
  setHTML("run-detail", empty(t("loading")));
  try {
    const records = await Promise.all([...state.pickedRuns].map(id => api("/api/runs/" + encodeURIComponent(id))));
    state.selectedRun = ""; state.record = null; renderRunList();
    renderSavedComparison(records);
  } catch (_) { setHTML("run-detail", empty(t("runReadError"))); }
});
$("run-filter").addEventListener("change", () => { state.runFilter = $("run-filter").value.trim().toUpperCase(); state.runCount = 50; refresh(); });
$("run-more").addEventListener("click", () => { state.runCount = Math.min(200, state.runCount + 50); refresh(); });
$("run-detail").addEventListener("click", async event => {
  const csvButton = event.target.closest?.("[data-csv]");
  if (csvButton && state.record) { exportCsv(csvButton.dataset.csv, state.record); return; }
  const goto = event.target.closest?.("[data-goto-tab]");
  if (goto) { showResearchTab(goto.dataset.gotoTab, true); return; }
  const button = event.target.closest?.("[data-export-run]") || event.target;
  if (!button.dataset.exportRun) return;
  button.disabled = true;
  try {
    const html = button.dataset.format === "html";
    const card = await api("/api/runs/" + encodeURIComponent(button.dataset.exportRun) + (html ? "/summary.html" : "/summary"), {}, 10000, html);
    const url = URL.createObjectURL(new Blob([html ? card : JSON.stringify(card, null, 2)], { type: html ? "text/html" : "application/json" }));
    try {
      const link = document.createElement("a");
      link.href = url; link.download = `paper-${button.dataset.exportRun}.${html ? "html" : "json"}`; link.click();
    } finally { URL.revokeObjectURL(url); }
  } catch (_) { state.apiError = true; renderFeed(); }
  finally { button.disabled = false; }
});
$("compare-result").addEventListener("click", selectSavedRun);
$("compare-form").addEventListener("submit", submitComparison);
$("validate-submit").onclick = event => submitComparison(event, true);
$("research-tick").onclick = () => controlResearch("tick");
$("research-jobs").addEventListener("click", event => {
  const button = event.target.closest?.("[data-research-action]") || event.target;
  if (button.dataset.researchAction) controlResearch(button.dataset.researchAction, button.dataset.job);
  else selectSavedRun(event);
});
$("compare-form").addEventListener("input", event => {
  const { slot, parameter } = event.target.dataset;
  if (parameter) { state.candidateParams[slot] ||= {}; state.candidateParams[slot][parameter] = event.target.value; }
  invalidateComparison();
});
for (const slot of ["first", "second"]) $("candidate-" + slot).addEventListener("change", () => {
  state.candidateParams[slot] = {}; invalidateComparison(); renderCandidate(slot);
});
$("compare-symbol").addEventListener("change", () => { invalidateComparison(); setupResearch($("compare-symbol").value); });
$("language-toggle").onclick = () => { lang = lang === "en" ? "fa" : "en"; remember("lang", lang); applyLang(); renderAlertToggle(); refresh(); };
$("theme-toggle").onclick = () => { theme = theme === "light" ? "dark" : "light"; remember("theme", theme); applyLang(); };
$("refresh-data").onclick = () => refresh();
$("retry").onclick = () => refresh();
$("ticket-example").onclick = () => {
  invalidateTicket();
  $("offline-ticket").value = JSON.stringify(syntheticTicket(), null, 2);
  renderTicketFields();
  $("offline-ticket").removeAttribute("aria-invalid");
  setHTML("ticket-output", `<p class="field-help">${esc(t("syntheticExample"))}</p>`);
};
$("preview-ticket").onclick = previewTicket;
async function writeOfflineReview(button, action, value) {
  button.disabled = true;
  const status = action === "record" ? $("ticket-output") : $("offline-review-status");
  try {
    const result = await api("/api/offline-ticket-reviews", { method: "POST", body: JSON.stringify({ action, value }) });
    if (action === "record" && currentPreview === value) setHTML("ticket-output", `<p role="status">${esc(t("journalSaved"))} · ${code(result.preview_sha256)}</p>`);
    else if (action === "review") status.textContent = `${t("journalSaved")} · ${result.state}`;
    await offlineReviews();
  } catch { if (action !== "record" || currentPreview === value) status.textContent = t("reviewWriteError"); }
  finally { if (button.isConnected) button.disabled = false; }
}
$("ticket-output").addEventListener("click", event => {
  const button = event.target.closest?.("#save-preview");
  if (button && currentPreview) writeOfflineReview(button, "record", currentPreview);
});
$("offline-review-events").addEventListener("click", event => {
  const button = event.target.closest?.("[data-review-key]");
  if (button) writeOfflineReview(button, "review", { preview_sha256: button.dataset.reviewKey, decision: button.dataset.decision });
});
$("offline-ticket").addEventListener("input", invalidateTicket);
$("ticket-fields").addEventListener("input", editTicketField);
$("ticket-fields").addEventListener("change", editTicketField);
$("ticket-editor-mode").addEventListener("click", event => {
  const button = event.target.closest?.("[data-editor]");
  if (!button) return;
  const useJson = button.dataset.editor === "json";
  if (!useJson) renderTicketFields();
  $("ticket-fields").hidden = useJson; $("ticket-json-panel").hidden = !useJson;
  document.querySelectorAll("[data-editor]").forEach(item => item.setAttribute("aria-pressed", String(item === button)));
});
$("rule-rows").addEventListener("click", event => {
  const button = event.target.closest?.("[data-disable]") || event.target, id = button.dataset.disable;
  if (!id || !confirm(`${t("disableConfirm")}\n${id}`)) return;
  changeRule(button, async () => { await api("/api/rules/" + encodeURIComponent(id) + "/disable", { method: "POST" }); $("rule-action-result").textContent = t("ruleSaved"); });
});
$("load-preset").onclick = () => {
  if (!confirm(t("presetConfirm"))) return;
  changeRule($("load-preset"), async () => { await api("/api/presets/usdt-irt-october-2026", { method: "POST" }); $("rule-action-result").textContent = t("presetSaved"); });
};
$("rule-import-submit").onclick = async () => {
  const input = $("rule-import"), button = $("rule-import-submit");
  if (state.savingRules) return;
  button.disabled = true; button.setAttribute("aria-busy", "true"); input.removeAttribute("aria-invalid");
  try {
    if (!Array.isArray(JSON.parse(input.value))) throw new Error("expected list");
    const result = await api("/api/rules/import", { method: "POST", body: input.value });
    $("rule-import-result").textContent = `${digits(result.imported)} ${t("imported")} · ${digits(list(result.quarantined).length)} ${t("quarantined")}`;
    await rules();
  } catch (_) { input.setAttribute("aria-invalid", "true"); $("rule-import-result").textContent = t("importError"); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); }
};
// Deep links: #research/<tab>[/<run id>] opens a research tab and, for runs, a saved run.
function route(hash) {
  const [name, tab, id] = hash.slice(1).split("/");
  if (name === "research" && researchTabs.includes(tab)) {
    showResearchTab(tab, false, false);
    if (tab === "runs" && /^[0-9a-f]{16}$/.test(id || "")) { state.selectedRun = state.pinnedRun = id; state.record = null; }
  }
  return name;
}
function linkResearch() {
  if (state.view !== "research") return;
  const id = researchTab === "runs" && state.selectedRun ? "/" + state.selectedRun : "";
  history.replaceState(null, "", `${location.pathname}${location.search}#research/${researchTab}${id}`);
}
window.addEventListener?.("hashchange", () => {
  const name = route(location.hash);
  if (!name || Object.hasOwn(viewKeys, name)) showView(name, true);
});
document.addEventListener("visibilitychange", () => { clearTimeout(pollTimer); if (!document.hidden) refresh(); });
$("demo-banner").hidden = !DEMO;
$("session-key-missing").hidden = Boolean(TOKEN);
$("rotate-key").addEventListener("click", async () => {
  try {
    TOKEN = (await api("/api/session/rotate", { method: "POST", body: "{}" })).token;
    try { sessionStorage.setItem("gym-token", TOKEN); } catch (_) {}
    setHTML("rotate-key-result", `${esc(t("rotatedKey"))} <code dir="ltr">${esc(location.origin + "/#t=" + TOKEN)}</code>`);
  } catch (_) { setHTML("rotate-key-result", esc(t("requestError"))); }
});
applyLang();
showView(route(location.hash));
