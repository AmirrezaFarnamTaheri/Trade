const { token: TOKEN, demo: DEMO } = JSON.parse(document.getElementById("gym-config").textContent);

const vocabulary = {
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
  runLimit: ["Latest 50 runs", "۵۰ اجرای آخر"], accountEyebrow: ["Your observation journal", "دفتر مشاهدات شما"],
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
  lastDecisions: ["Last 100 decisions", "۱۰۰ تصمیم آخر"], decisionHelp: ["Expand a decision for its snapshot, marks, and matching paper order.", "برای دیدن تصویر بازار، نتایج و سفارش آزمایشی مرتبط، تصمیم را باز کنید."],
  noDecisions: ["No strategy decisions were recorded.", "تصمیمی از راهبرد ثبت نشده است."],
  fullRecord: ["Full record", "رکورد کامل"], accountNotConfigured: ["No account observation configured", "مشاهدهٔ حساب پیکربندی نشده است"],
  accountSetupHelp: ["Private account observations are not configured on this server. Market observation and paper research work without an account; never paste credentials here.", "مشاهدات خصوصی حساب در این سرور پیکربندی نشده است. مشاهدهٔ بازار و پژوهش آزمایشی به حساب نیاز ندارند؛ اطلاعات ورود را اینجا وارد نکنید."],
  accountObserved: ["Observed · unverified · unmanaged", "مشاهده‌شده · تأییدنشده · مدیریت‌نشده"],
  accountError: ["Account observation unavailable. Previously shown balances have been cleared.", "مشاهدهٔ حساب در دسترس نیست. موجودی‌های قبلی از نمایش پاک شده‌اند."],
  accountBalance: ["Observed balances", "موجودی‌های مشاهده‌شده"],
  accountBalanceNote: ["Venue values and locked amounts are observations, not spendable or protectable balances.", "مقدار و مبلغ بلوکه‌شدهٔ صرافی فقط مشاهده‌اند؛ موجودی قابل خرج یا قابل حفاظت نیستند."],
  asset: ["Asset", "دارایی"], venueValue: ["Venue value", "مقدار صرافی"], venueLocked: ["Locked", "بلوکه‌شده"],
  accountOrders: ["External / manual orders", "سفارش‌های خارجی / دستی"], clientId: ["Client ID", "شناسهٔ سفارش کاربر"],
  rawStatus: ["Venue status", "وضعیت صرافی"], settlement: ["Settlement", "تسویه"], filledObserved: ["Observed filled amount", "مقدار پرشدهٔ مشاهده‌شده"],
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
  backupLead: ["Encrypted ledger recovery uses the existing protected-console workflow.", "بازیابی رمزگذاری‌شدهٔ دفتر از مسیر کنسول حفاظت‌شده انجام می‌شود."], backupNotConnected: ["Status not connected", "وضعیت متصل نیست"],
  backupWorkflow: ["Create an encrypted backup", "ساخت پشتیبان رمزگذاری‌شده"], backupHelp: ["Use a pre-existing directory on an independent mounted volume. Enter the recovery passphrase only in the protected console.", "از پوشهٔ موجود روی دیسک مستقل استفاده کنید. عبارت بازیابی را فقط در کنسول حفاظت‌شده وارد کنید."],
  restoreWorkflow: ["Restore to a new ledger", "بازیابی در دفتر جدید"], restoreHelp: ["The destination must not exist. Restoration verifies the ledger and leaves execution disarmed.", "مقصد نباید وجود داشته باشد. بازیابی دفتر را بررسی می‌کند و اجرا غیرفعال می‌ماند."], recoveryTruth: ["Recovery evidence", "شواهد بازیابی"],
  backupStatusHelp: ["The web API does not expose archive inventory or last successful recovery. No current backup or integrity claim can be made here.", "رابط وب فهرست بایگانی یا آخرین بازیابی موفق را ارائه نمی‌کند؛ اینجا نمی‌توان وضعیت پشتیبان یا سلامت آن را تأیید کرد."],
  integrityFirst: ["Integrity before use", "صحت‌سنجی پیش از استفاده"], integrityHelp: ["A successful decrypt is not trading permission. Signed manifest checks require an independently pinned public key.", "رمزگشایی موفق مجوز معامله نیست. بررسی مانیفست امضاشده به کلید عمومی مستقل و از پیش تعیین‌شده نیاز دارد."],
  privacy: ["Privacy", "حریم خصوصی"], backupPrivacy: ["Recovery passphrases and venue credentials never belong in a browser form.", "عبارت بازیابی و اطلاعات ورود صرافی را هرگز در فرم مرورگر وارد نکنید."],
  structuredForm: ["Structured form", "فرم ساختاریافته"], jsonEditor: ["JSON editor", "ویرایشگر JSON"], ticketEditor: ["Ticket editor", "ویرایشگر سفارش"],
  symbol: ["Symbol", "نماد"], side: ["Side", "جهت"], intent: ["Intent", "هدف"], worst_price: ["Worst price", "قیمت بدترین حالت"], fee_rate: ["Fee rate", "نرخ کارمزد"], operator_quote_cap: ["Operator quote cap", "سقف ارز مظنهٔ اپراتور"],
  available_quote: ["Declared quote balance", "موجودی اعلامی ارز مظنه"], available_base: ["Declared base balance", "موجودی اعلامی ارز پایه"], minimum_quote: ["Minimum quote notional", "حداقل ارزش سفارش"],
  observed_at: ["Observed at · zoned ISO", "زمان مشاهده · ISO با منطقه"], expires_at: ["Expires at · zoned ISO", "زمان انقضا · ISO با منطقه"], snapshot_seq: ["Snapshot sequence", "شمارهٔ تصویر"], quote_age_ms: ["Quote age · ms (0–2000)", "سن مظنه · میلی‌ثانیه (۰ تا ۲۰۰۰)"],
  previewChanged: ["Ticket changed. Preview again to calculate costs for these inputs.", "سفارش تغییر کرد. برای محاسبهٔ هزینهٔ این ورودی‌ها دوباره پیش‌نمایش بگیرید."],
  BUY: ["Buy", "خرید"], SELL: ["Sell", "فروش"], ENTRY: ["Entry", "ورود"], EXIT: ["Exit", "خروج"],
  savedRunCount: ["Saved paper runs", "اجراهای آزمایشی ذخیره‌شده"], runCountNote: ["Latest 50 records", "۵۰ رکورد آخر"], executionStatus: ["Autonomous execution", "اجرای خودکار"],
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
const state = { view: "overview", markets: null, quote: "", filter: "", expanded: "", runs: [],
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
function when(value, dateOnly = false) {
  if (!value) return t("none");
  const stamp = new Date(value);
  if (!Number.isFinite(stamp.getTime())) return t("unknown");
  return new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", {
    timeZone: "Asia/Tehran", year: "numeric", month: "short", day: "numeric",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit" }),
  }).format(stamp);
}
const list = value => Array.isArray(value) ? value : [];
const code = value => `<bdi dir="ltr">${esc(value ?? t("none"))}</bdi>`;
const amount = value => `<bdi dir="ltr">${num(value)}</bdi>`;
const label = value => esc(t(String(value ?? "unknown")));
const chip = (text, kind = "warn") => `<span class="chip chip-${kind}">${esc(text)}</span>`;
const empty = (title, help = "") => `<div class="empty-state"><p class="empty-title">${esc(title)}</p>${help ? `<p class="field-help">${esc(help)}</p>` : ""}</div>`;
const json = value => `<pre class="output mono" dir="ltr">${esc(JSON.stringify(value, null, 2))}</pre>`;
const disclosure = (title, value, key) => `<details class="disclosure" data-key="${esc(key)}"><summary>${esc(title)}</summary>${json(value)}</details>`;
const stat = (name, value, note = "") => `<div class="stat"><span class="stat-label">${esc(name)}</span><strong class="stat-value">${value}</strong>${note ? `<span class="stat-note">${esc(note)}</span>` : ""}</div>`;
const keyValues = rows => `<dl class="key-values">${rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${value}</dd></div>`).join("")}</dl>`;
function table(headings, rows, fallback) {
  if (!rows.length) return empty(fallback || t("nothing"));
  return `<div class="table-wrap" tabindex="0"><table class="data"><thead><tr>${headings.map(h => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
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
    if (!response.ok) throw new Error(t("requestError"));
    return asText ? await response.text() : await response.json();
  } catch (_) {
    // Server errors may contain submitted material; show only a fixed local message.
    throw new Error(t("requestError"));
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
  if (state.health) renderHealth(state.health);
  if (state.rules) renderRules(state.rules);
  renderOverview(); renderTicketFields(); renderFeed(); updateClock();
  if (state.researchSetup) { for (const slot of ["first", "second"]) renderCandidate(slot); renderCoverage(); }
  renderComparison();
  if (state.researchState) renderResearchJobs(state.researchState);
  if (state.view === "models") window.gymModels?.mount(api, esc);
  if (state.view === "research") window.gymResearch?.mount(api, esc);
}

const invalidQuoteFlags = new Set(["STALE", "CROSSED", "ZERO_SPREAD", "NON_FINITE", "NON_POSITIVE"]);
function healthyQuote(market) {
  return market.qualified === true;
}
function eligibility(verdict) {
  if (verdict?.allowed === true) return chip(t("eligible"), list(verdict.warnings).length ? "warn" : "ok");
  return verdict?.allowed === false ? chip(t("blocked"), "bad") : chip(t("notEvaluated"));
}
function ruleReference(rule) {
  return `<li><strong>${esc(rule.name || rule.rule_id || t("unknown"))}</strong>${rule.why ? `<p>${esc(rule.why)}</p>` : ""}${keyValues([
    [t("classification"), code(rule.class)], [t("family"), code(rule.family)], [t("status"), label(rule.status)],
    [t("source"), esc(rule.source)], [t("confirmed"), esc(when(rule.confirmed))],
  ])}</li>`;
}
function verdictDetails(title, verdict) {
  if (!verdict) return `<section><h3>${esc(title)}</h3>${empty(t("notEvaluated"))}</section>`;
  return `<section><h3>${esc(title)} ${eligibility(verdict)}</h3><h4>${esc(t("blockers"))}</h4>${list(verdict.blockers).length
    ? `<ul class="rule-references">${list(verdict.blockers).map(ruleReference).join("")}</ul>` : `<p class="muted">${esc(t("noBlockers"))}</p>`}
    ${list(verdict.warnings).length ? `<h4>${esc(t("warnings"))}</h4><ul class="rule-references">${verdict.warnings.map(ruleReference).join("")}</ul>` : ""}
    ${keyValues([[t("nextRuleChange"), verdict.next_change ? esc(when(verdict.next_change)) : esc(t("noRuleChange"))],
      [t("quotaRemaining"), amount(verdict.quota_remaining)], [t("ruleVersion"), num(verdict.ruleset_version)]])}
    <p class="field-help">${esc(t("changeNote"))}</p></section>`;
}
function renderMarkets() {
  const data = state.markets;
  if (!data) return;
  const markets = list(data.markets), search = state.filter.trim().toLocaleLowerCase();
  const shown = markets.filter(market => (!state.quote || market.quote === state.quote)
    && (!search || [market.symbol, market.base, market.quote, ...Object.values(market.names || {})].some(value => String(value ?? "").toLocaleLowerCase().includes(search))));
  setHTML("market-summary", stat(t("observedPairs"), num(markets.length), t("observedPairsNote"))
    + stat(t("healthyQuotes"), num(markets.filter(healthyQuote).length), t("healthyQuotesNote"))
    + stat(t("eligibleEntries"), num(markets.filter(market => market.act?.entry?.allowed === true).length), t("eligibleEntriesNote")));
  const fx = data.fx, fxStatus = fx?.status === "LIVE" ? "liveQuote" : fx?.status === "STALE_CLOSED" ? "fxClosed" : "unavailable";
  setHTML("fx-summary", `<span class="stat-label">${esc(t("fxLabel"))}</span><strong class="stat-value">${amount(fx?.mid)}</strong>${chip(t(fxStatus), fx?.status === "LIVE" ? "ok" : "warn")}<p class="field-help">${esc(t("fxNote"))}</p>`);
  $("market-count").textContent = `${t("showing")} ${digits(shown.length)} ${t("of")} ${digits(markets.length)} ${t("pairs")}`;
  $("market-updated").textContent = `${t("updated")} ${when(data.now)}`;
  $("demo-banner").hidden = !data.demo;
  document.querySelectorAll("[data-quote]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.quote === state.quote)));
  if (!shown.length) {
    setHTML("market-rows", `<tr><td colspan="8">${empty(t(markets.length ? "noMatches" : "noMarkets"), t(markets.length ? "noMatchesHelp" : "noMarketsHelp"))}</td></tr>`);
    return;
  }
  setHTML("market-rows", shown.map(market => {
    const flags = list(market.flags), trade = market.last_trade, expanded = state.expanded === market.symbol;
    const quality = !market.bid || !market.ask ? chip(t("quoteMissing"))
      : flags.length ? flags.map(flag => chip(t(flag), invalidQuoteFlags.has(flag) ? "bad" : "warn")).join(" ") : healthyQuote(market) ? chip(t("healthy"), "ok") : chip(t("notEvaluated"), "warn");
    const name = market.names?.[lang] || market.symbol;
    const id = "market-detail-" + encodeURIComponent(market.symbol);
    return `<tr${expanded ? ' class="is-expanded"' : ""}><td><button type="button" class="symbol-button" data-market="${esc(market.symbol)}" data-focus="market-${esc(market.symbol)}" aria-expanded="${expanded}"${expanded ? ` aria-controls="${esc(id)}"` : ""}><span class="token-mark" aria-hidden="true">${esc((market.base || market.symbol || "?").slice(0, 1))}</span><span class="pair-name"><strong>${esc(name)}</strong><span class="sub">${code(market.symbol)} <span class="quote">${code(market.quote)}</span></span></span></button></td>
      <td class="num">${amount(market.bid)}</td><td class="num">${amount(market.ask)}</td><td class="num">${amount(market.spread_bps)}</td>
      <td class="num">${trade ? `${amount(trade.price)}<span class="sub">${amount(trade.qty)} ${code(market.base)} · ${esc(when(trade.ts))}</span>` : t("none")}</td>
      <td>${quality}${market.book_age_s != null ? `<span class="sub">${num(market.book_age_s)} ${esc(t("seconds"))}</span>` : ""}</td>
      <td>${eligibility(market.act?.entry)}</td><td>${eligibility(market.act?.exit)}</td></tr>
      ${expanded ? `<tr class="market-detail-row"><td colspan="8"><section class="market-detail" id="${esc(id)}" aria-label="${esc(t("pairDetails") + " " + market.symbol)}">
        ${keyValues([[t("bestBidQuantity"), `${amount(market.bid_qty)} ${code(market.base)}`], [t("bestAskQuantity"), `${amount(market.ask_qty)} ${code(market.base)}`],
          [t("absoluteSpread"), `${amount(market.spread)} ${code(market.quote)}`], ...(market.unit ? [[t("unitEpoch"), `${code(market.unit.code)} · ${num(market.unit.epoch)}`]] : [])])}
        <h3>${esc(t("observedDepth"))}</h3><p class="field-help">${esc(t("depthNote"))}</p>${market.liquidity?.status === "AVAILABLE" ? table([t("depthBand"), `${t("bidDepth")} · ${market.base}`, `${t("askDepth")} · ${market.base}`, t("imbalance")], market.liquidity.bands.map(band => [num(band.width_bps), amount(band.bid_base), amount(band.ask_base), amount(band.imbalance)])) : empty(t("unavailable"))}
        <div class="detail-grid">${verdictDetails(t("entry"), market.act?.entry)}${verdictDetails(t("exit"), market.act?.exit)}</div></section></td></tr>` : ""}`;
  }).join(""));
}

function renderRunList() {
  setHTML("run-list", state.runs.map(run => `<li><button type="button" class="run-link" data-run="${esc(run.run_id)}" data-focus="run-${esc(run.run_id)}" aria-pressed="${run.run_id === state.selectedRun}"><strong>${code(run.inputs?.symbol || run.result?.symbol || run.run_id)}</strong><span>${esc(when(run.inputs?.from, true))}</span><span class="sub">${code(run.run_id)} · ${esc(t(run.inputs?.store === "demo" ? "synthetic" : "liveData"))}</span></button></li>`).join(""));
}
function curveFigure(result) {
  const points = list(result.curve).filter(point => Array.isArray(point) && point.length > 1 && Number.isFinite(Number(point[1])));
  if (!points.length) return empty(t("noCurve"));
  const values = points.map(point => Number(point[1])), lo = Math.min(...values), hi = Math.max(...values);
  const first = Date.parse(points[0][0]), last = Date.parse(points[points.length - 1][0]);
  const coordinates = points.map((point, i) => {
    const timestamp = Date.parse(point[0]);
    const x = 100 + 640 * (last > first && Number.isFinite(timestamp) ? (timestamp - first) / (last - first) : i / Math.max(1, points.length - 1));
    const y = hi === lo ? 116 : 28 + (hi - values[i]) * 176 / (hi - lo);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const title = `${t("equityCurve")} · ${result.quote || ""}`;
  const tick = value => new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-GB", { maximumFractionDigits: 2 }).format(value);
  return `<figure class="equity-figure"><svg class="chart" viewBox="0 0 780 258" role="img" aria-label="${esc(title)}" dir="ltr"><title>${esc(title)}</title>
    <line class="chart-base" x1="100" y1="28" x2="740" y2="28"/><line class="chart-base" x1="100" y1="204" x2="740" y2="204"/>
    <text x="91" y="33" text-anchor="end">${esc(tick(hi))}</text><text x="91" y="209" text-anchor="end">${esc(tick(lo))}</text>
    <text x="100" y="244">${esc(when(points[0][0], true))}</text><text x="740" y="244" text-anchor="end">${esc(when(points[points.length - 1][0], true))}</text>
    <polygon class="chart-area" points="100,204 ${coordinates} 740,204"/><polyline class="chart-line" points="${coordinates}" fill="none"/><text x="100" y="14">${esc(result.quote || "")}</text></svg><figcaption class="field-help">${esc(t("curveNote"))}</figcaption></figure>`;
}
function waterfallFigure(entries, quote) {
  if (!entries.length || entries.some(([, value]) => !Number.isFinite(Number(value)))) return "";
  let accumulated = 0;
  const steps = entries.map(([key, value]) => {
    const start = key === "net" ? 0 : accumulated;
    const end = start + Number(value);
    if (key !== "net") accumulated = end;
    return { key, start, end, value: Number(value) };
  });
  const low = Math.min(0, ...steps.flatMap(step => [step.start, step.end]));
  const high = Math.max(0, ...steps.flatMap(step => [step.start, step.end]));
  const y = value => 35 + (high - value) * 145 / (high - low || 1);
  const width = 600 / steps.length;
  const tick = value => new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-GB", { maximumFractionDigits: 2 }).format(value);
  return `<figure class="equity-figure"><svg class="chart waterfall-chart" viewBox="0 0 780 250" role="img" aria-label="${esc(t("costWaterfall") + " · " + quote)}" dir="ltr"><title>${esc(t("costWaterfall"))}</title><line class="chart-base" x1="80" y1="${y(0)}" x2="750" y2="${y(0)}"/>${steps.map((step, i) => {
    const x = 95 + i * width, top = Math.min(y(step.start), y(step.end)), height = Math.max(1, Math.abs(y(step.start) - y(step.end)));
    return `<rect x="${x}" y="${top}" width="${width * .55}" height="${height}" class="waterfall-bar ${step.value < 0 ? "neg" : "pos"}"/><text x="${x + width * .275}" y="${top - 9}" text-anchor="middle">${esc(tick(step.value))}</text><text x="${x + width * .275}" y="218" text-anchor="middle">${label(step.key)}</text>`;
  }).join("")}<text x="80" y="20">${esc(quote)}</text></svg></figure>`;
}
function renderRun(record) {
  if (!record) return;
  const result = record.result || {}, inputs = record.inputs || {}, end = result.end || {}, quote = result.quote || "";
  const waterfall = end.waterfall || {}, entries = Object.entries(waterfall);
  const scale = Math.max(...entries.map(([, value]) => Math.abs(Number(value))).filter(Number.isFinite), 1);
  const costs = entries.length ? `<div class="bars">${entries.map(([key, value]) => `<div class="cost-row"><span>${label(key)}</span><div class="bar-track" aria-hidden="true"><span class="bar ${String(value).startsWith("-") ? "neg" : "pos"}" style="width:${Math.min(100, Math.max(0, Math.abs(Number(value)) / scale * 100))}%"></span></div><strong class="num">${amount(value)}</strong></div>`).join("")}</div>` : empty(t("noCost"));
  const baselines = Object.entries({ strategy: result, ...(record.baselines || {}) }).map(([name, baseline]) => [esc(name),
    baseline.end ? `${amount(baseline.end.net)} ${code(quote)}` : `${esc(t("unavailable"))}<span class="sub">${esc(baseline.unavailable || "")}</span>`, amount(baseline.end?.net_usdt_eq), num(baseline.fills)]);
  const ranking = record.ranking || {};
  const evidence = record.evidence;
  const decisions = list(result.decisions).slice(-100).reverse();
  setHTML("run-detail", `<header class="run-heading"><div><span class="eyebrow">${esc(inputs.store === "demo" ? t("synthetic") : t("paperOnly"))}</span><h2>${code(result.symbol || inputs.symbol)} <span class="muted">${esc(result.strategy || "")}</span></h2><p class="field-help">${esc(when(inputs.from))} → ${esc(when(inputs.to))} · ${code(inputs.resolution)} · ${code(result.session?.state || record.mode || "PAPER")}</p></div>${chip(t("noCapital"))}</header>
    <div class="stats">${stat(t("equity"), `${amount(end.equity)} <small>${esc(quote)}</small>`)}${stat(t("net"), `${amount(end.net)} <small>${esc(quote)}</small>`)}${stat(t("fills"), num(result.fills))}${stat(t("observations"), `${num(result.qualified)} <small>/ ${num(result.observations)}</small>`)}</div>
    <section class="panel"><h3 class="panel-title">${esc(t("equityCurve"))}</h3>${curveFigure(result)}${keyValues([[t("sampledDrawdown"), evidence?.sampled_drawdown?.status === "AVAILABLE" ? `${amount(evidence.sampled_drawdown.maximum_percent)} %` : esc(t("unavailable"))]])}<p class="field-help">${esc(t("drawdownNote"))}</p></section>
    <section class="panel"><h3 class="panel-title">${esc(t("costWaterfall"))} <span class="muted">${esc(quote)}</span></h3>${waterfallFigure(entries, quote)}${costs}<p class="field-help">${esc(t("updated"))} ${esc(when(end.mark_time))}</p></section>
    <section class="panel"><h3 class="panel-title">${esc(t("baselineTitle"))}</h3><p class="field-help">${esc(t("baselineNote"))}</p>${table([t("strategy"), `${t("net")} · ${quote}`, t("usdtEquivalent"), t("fills")], baselines)}${record.fx ? keyValues([[t("fxLabel"), `${amount(record.fx.start)} → ${amount(record.fx.end)}`], [t("status"), `${label(record.fx.start_status)} → ${label(record.fx.end_status)}`], [t("source"), esc(record.fx.basis)]]) : ""}</section>
    <section class="panel"><h3 class="panel-title">${esc(t("rankingTitle"))}</h3><p class="field-help">${esc(t("rankingNote"))}</p>${table([t("rank"), t("strategy"), t("usdtEquivalent"), t("fills")], list(ranking.active).map(row => [num(row.rank), esc(row.name), amount(row.net_usdt_eq), num(row.fills)]), t("noActiveRank"))}
      ${list(ranking.abstainers).length ? `<h4>${esc(t("abstainers"))}</h4>${table([t("strategy"), `${t("net")} · ${quote}`, t("usdtEquivalent")], ranking.abstainers.map(row => [esc(row.name), amount(row.net_quote), amount(row.net_usdt_eq)]))}` : ""}</section>
    <section class="panel"><div class="panel-heading"><h3 class="panel-title">${esc(t("evidenceTitle"))}</h3>${chip(t("noCapital"))}</div>${evidence ? `<p>${esc(evidence.primary_limitation)}</p>${keyValues([[t("roundTrips"), num(evidence.completed_round_trips)], [t("claimCeiling"), code(evidence.claim_ceiling)], [t("evidenceGate"), esc(t(evidence.gate_eligible === true ? "yes" : "no"))]])}` : `<p>${esc(t("noEvidence"))}</p>`}
      ${list(record.warnings || evidence?.warnings).length ? `<ul class="evidence-warnings">${list(record.warnings || evidence?.warnings).map(warning => `<li>${esc(warning)}</li>`).join("")}</ul>` : ""}
      <button type="button" class="button" data-export-run="${esc(record.run_id)}">${esc(t("exportSummary"))}</button>
      <button type="button" class="button" data-export-run="${esc(record.run_id)}" data-format="html">${esc(t("exportHtml"))}</button><p class="field-help">${esc(t("summaryNote"))}</p>
      ${disclosure(t("reportDetails"), { report: evidence || null, capital_decisions: record.capital_decisions || [] }, "economic-evidence")}${disclosure(t("runInputs"), { inputs, session: result.session, fx: record.fx, outputs_digest: record.outputs_digest }, "run-inputs")}</section>
    <section class="panel"><h3 class="panel-title">${esc(t("lastDecisions"))}</h3><p class="field-help">${esc(t("decisionHelp"))}</p>${decisions.length ? decisions.map((decision, i) => `<details class="decision disclosure" data-key="decision-${esc(decision.t)}-${esc(decision.order || i)}"><summary><span>${esc(when(decision.t))}</span> <strong>${esc(decision.action)}</strong> <span class="muted">${list(decision.reasons).map(esc).join("; ")}</span></summary>${json({ ...decision, order: list(result.orders).find(order => order.ref === decision.order) || null })}</details>`).join("") : empty(t("noDecisions"))}</section>`);
}
function renderCandidate(slot) {
  const entry = list(state.researchSetup?.strategies).find(item => item.id === $("candidate-" + slot).value);
  if (!entry) return;
  const names = { fast: "parameterFast", slow: "parameterSlow", lookback: "parameterLookback", entry_bps: "parameterEntry", confirmation: "parameterConfirmation", reference: "parameterReference", deviations: "parameterDeviations" };
  const values = state.candidateParams[slot] || {};
  setHTML("candidate-" + slot + "-params", Object.entries(entry.parameters.properties).map(([key, spec]) => {
    const id = `parameter-${slot}-${key}`, value = values[key] ?? spec.default;
    const attrs = `id="${id}" data-slot="${slot}" data-parameter="${esc(key)}" required dir="ltr"`;
    const input = spec.enum ? `<select ${attrs}>${spec.enum.map(option => `<option${option === value ? " selected" : ""}>${esc(option)}</option>`).join("")}</select>`
      : `<input class="input" ${attrs} type="${spec.type === "integer" ? "number" : "text"}" value="${esc(value)}" ${spec.type === "integer" ? `min="${spec.minimum}" max="${spec.maximum}" step="1"` : `pattern="[A-Z0-9]{2,24}" maxlength="24"`}>`;
    return `<label for="${id}"><span>${esc(t(names[key] || key))}</span>${input}</label>`;
  }).join(""));
}
function renderCoverage() {
  const data = state.researchSetup?.coverage;
  if (!data) return;
  setHTML("paper-coverage", `<p><strong>${esc(t("coverageTitle"))} · ${code(data.symbol)}</strong> ${esc(when(data.from))} → ${esc(when(data.to))}</p><p>${esc(t("recordedObservations"))}: ${num(data.observations)} · ${esc(t("coverageGaps"))}: ${num(data.gaps_over_120s)}</p><p>${esc(t("coverageNote"))}</p>`);
}
async function setupResearch(symbol = "") {
  $("comparison-fields").disabled = true;
  try {
    const setup = await api("/api/research" + (symbol ? "?symbol=" + encodeURIComponent(symbol) : ""));
    if (symbol && $("compare-symbol").value !== symbol) return;
    const initial = !state.researchSetup;
    state.researchSetup = setup;
    if (initial) {
      $("compare-symbol").innerHTML = list(setup.symbols).map(item => `<option>${esc(item)}</option>`).join("");
      $("compare-symbol").value = setup.coverage.symbol;
      $("compare-fee").value = setup.defaults.fee_rate;
      for (const [index, slot] of ["first", "second"].entries()) {
        $("candidate-" + slot).innerHTML = list(setup.strategies).map(entry => `<option value="${esc(entry.id)}">${esc(entry.title)}</option>`).join("");
        $("candidate-" + slot).value = setup.strategies[index]?.id || setup.strategies[0]?.id || "";
        renderCandidate(slot);
      }
    }
    $("compare-cash").value = setup.coverage.symbol.endsWith("TMN") ? "300000000" : "1000";
    for (const [field, value] of [["from", setup.coverage.from], ["to", setup.coverage.to]]) {
      $("compare-" + field).value = value ? new Date(value).toISOString().slice(0, 19) : "";
    }
    $("comparison-fields").disabled = !setup.coverage.observations;
    renderCoverage();
  } catch (_) {
    if (symbol && $("compare-symbol").value !== symbol) return;
    $("comparison-fields").disabled = true; $("paper-coverage").textContent = t("researchUnavailable");
  }
}
function invalidateComparison() {
  comparisonRevision += 1;
  const hadResult = state.comparison !== null || state.comparing;
  state.comparison = null;
  if (hadResult) setHTML("compare-result", empty(t("comparisonChanged")));
}
function renderComparison() {
  $("compare-submit").textContent = t(state.comparing ? "comparing" : "compareAction");
  const data = state.comparison;
  if (!data) return;
  if (["TEMPORAL_VALIDATION", "MULTI_WINDOW_VALIDATION"].includes(data.mode)) {
    const windowText = window => `${esc(when(window.from))} → ${esc(when(window.to))}`;
    const windows = data.mode === "MULTI_WINDOW_VALIDATION" ? list(data.folds) : [data];
    setHTML("compare-result", `<section class="ticket-result"><h3>${esc(t("validationTitle"))} · ${code(data.validation_id)}</h3>${keyValues([
      [t("status"), label(data.status)], [t("validationWindows"), num(windows.length)],
    ])}<p class="field-help">${esc(t("validationNote"))}</p>${table([t("validationWindow"), t("status"), t("selectionWindow"), t("holdoutWindow"), t("selectedCandidate")], windows.map((fold, index) => [num(index + 1), label(fold.status), windowText(fold.windows.selection), windowText(fold.windows.holdout), code(fold.selected?.strategy)]))}${table([t("strategy"), t("time"), t("net"), t("inspectRun")], list(data.runs).map(record => [code(record.inputs.strategy), esc(when(record.inputs.to)), amount(record.result.end?.net), `<button type="button" class="button button-small" data-run="${esc(record.run_id)}">${esc(t("inspectRun"))}</button>`]))}${disclosure(t("runInputs"), { folds: windows, trial_count: data.trial_count, limitation: data.limitation }, "validation-inputs")}</section>`);
    return;
  }
  const quote = data.runs[0]?.result?.quote || "";
  setHTML("compare-result", `<section class="ticket-result"><h3>${esc(t("compareTitle"))} · ${code(data.comparison_id)}</h3><p>${esc(t("comparisonLimit"))}</p>${table([t("strategy"), `${t("net")} · ${quote}`, t("usdtEquivalent"), t("fills"), t("inspectRun")], list(data.runs).map(record => [code(record.inputs.strategy), amount(record.result.end?.net), amount(record.result.end?.net_usdt_eq), num(record.result.fills), `<button type="button" class="button button-small" data-run="${esc(record.run_id)}">${esc(t("inspectRun"))}</button>`]))}<h4>${esc(t("rankingTitle"))}</h4>${table([t("rank"), t("strategy"), t("usdtEquivalent")], list(data.ranking?.active).map(row => [num(row.rank), esc(row.name), amount(row.net_usdt_eq)]), t("noActiveRank"))}${disclosure(t("runInputs"), { shared: data.shared_inputs, candidates: data.runs.map(record => ({ run_id: record.run_id, config_hash: record.inputs.config_hash, params: record.inputs.params })) }, "comparison-inputs")}</section>`);
}
async function submitComparison(event, validation = false) {
  event.preventDefault();
  if (state.comparing || !state.researchSetup || $("comparison-fields").disabled || $("compare-form").reportValidity?.() === false) return;
  const revision = comparisonRevision;
  const inputSignature = () => JSON.stringify([[...$("compare-form").querySelectorAll("input, select")].map(input => input.value), state.candidateParams]);
  const signature = inputSignature();
  const candidates = ["first", "second"].map(slot => {
    const strategy = $("candidate-" + slot).value;
    const entry = state.researchSetup.strategies.find(item => item.id === strategy);
    const params = Object.fromEntries(Object.entries(entry.parameters.properties).map(([key, spec]) => {
      const value = state.candidateParams[slot]?.[key] ?? spec.default;
      return [key, spec.type === "integer" ? Number(value) : value];
    }));
    return { strategy, params };
  });
  state.comparison = null; state.comparing = true; $("compare-submit").disabled = true; $("validate-submit").disabled = true; $("compare-submit").setAttribute("aria-busy", "true");
  setHTML("compare-result", empty(t("comparing"))); renderComparison();
  try {
    const folds = Number($("validation-folds").value);
    const payload = { symbol: $("compare-symbol").value,
      from: $("compare-from").value + "Z", to: $("compare-to").value + "Z", resolution: $("compare-resolution").value,
      cash: $("compare-cash").value, fee_rate: $("compare-fee").value, latency_ms: 500, candidates };
    if (validation) payload.folds = folds;
    const data = await api(validation ? "/api/validate" : "/api/compare", { method: "POST", body: JSON.stringify(payload) }, 120000);
    const expected = validation ? (folds === 1 ? "TEMPORAL_VALIDATION" : "MULTI_WINDOW_VALIDATION") : "COMPARE";
    if (data.mode !== expected || data.authority !== "PAPER_ONLY" || data.funded_authority !== false || data.order_submitted !== false) throw new Error("unsafe comparison response");
    if (revision === comparisonRevision && signature === inputSignature()) { state.comparison = data; renderComparison(); }
    else if (revision === comparisonRevision) invalidateComparison();
    await research();
  } catch (_) {
    if (revision === comparisonRevision && signature !== inputSignature()) invalidateComparison();
    else if (revision === comparisonRevision) setHTML("compare-result", empty(t("compareError")));
  }
  finally { state.comparing = false; $("compare-submit").disabled = false; $("validate-submit").disabled = false; $("compare-submit").removeAttribute("aria-busy"); renderComparison(); }
}

async function research() {
  if (!state.researchSetup) await setupResearch();
  state.runs = list(await api("/api/runs")).slice(0, 50);
  if (!state.runs.some(run => run.run_id === state.selectedRun)) { state.selectedRun = state.runs[0]?.run_id || ""; state.record = null; }
  renderRunList();
  if (!state.selectedRun) {
    setHTML("run-detail", `<section class="panel">${empty(t("noRuns"), t("noRunsHelp"))}<p class="field-help">${esc(t("demoRunHelp"))}</p><pre class="output mono" dir="ltr">uv run gymctl demo-seed\nuv run gymctl paper BTCTMN --demo</pre></section>`);
    return;
  }
  if (state.record?.run_id === state.selectedRun) { renderRun(state.record); return; }
  const id = state.selectedRun;
  setHTML("run-detail", empty(t("loading")));
  try {
    const record = await api("/api/runs/" + encodeURIComponent(id));
    if (state.selectedRun === id) { state.record = record; renderRun(record); }
  } catch (_) { if (state.selectedRun === id) setHTML("run-detail", empty(t("runReadError"))); throw new Error(t("requestError")); }
}

function renderResearchJobs(data) {
  const hypotheses = new Map(list(data.hypotheses).map(row => [row.id, row]));
  const jobs = list(data.jobs);
  $("research-tick").disabled = state.researchBusy || !jobs.some(job => job.enabled === true);
  setHTML("research-jobs", table([t("strategy"), t("symbol"), t("status"), t("nextResearchRun"), t("lastResearchRun"), t("researchRetry"), t("actions")], jobs.map(job => {
    const hypothesis = hypotheses.get(job.hypothesis_id), action = job.enabled ? "pause" : "resume";
    return [code(hypothesis?.strategy), code(hypothesis?.symbol), esc(t(job.enabled ? "researchEnabled" : "researchPaused")),
      esc(when(job.next_at)), job.last_report?.run_id ? `<button type="button" class="button button-small" data-run="${esc(job.last_report.run_id)}">${esc(t("inspectRun"))}</button>` : label(job.last_report?.status), esc(when(job.last_report?.retry_at)),
      `<button type="button" class="button button-small" data-research-action="${action}" data-job="${esc(job.id)}" data-focus="research-${esc(job.id)}"${state.researchBusy ? " disabled" : ""}>${esc(t(action === "pause" ? "researchPause" : "researchResume"))}</button>`];
  }), t("noResearchJobs")));
  setHTML("research-alerts", table([t("time"), t("status"), t("researchRetry")], list(data.alerts).slice(0, 20).map(alert => [esc(when(alert.due_at)), label(alert.kind), esc(when(alert.retry_at))]), t("noResearchAlerts")));
}
async function researchJobs() {
  try {
    const data = await api("/api/research-state");
    if (data.authority !== "PAPER_ONLY" || data.funded_authority !== false || data.order_submitted !== false) throw new Error("unsupported research authority");
    state.researchState = data; renderResearchJobs(data);
  } catch (_) {
    state.researchState = null;
    $("research-tick").disabled = true;
    setHTML("research-jobs", empty(t("researchStateError")));
    throw new Error(t("requestError"));
  }
}
async function controlResearch(action, id = "") {
  if (state.researchBusy || !["tick", "pause", "resume"].includes(action)) return;
  state.researchBusy = true;
  if (state.researchState) renderResearchJobs(state.researchState);
  try {
    const path = action === "tick" ? "/api/research/tick" : `/api/research/jobs/${encodeURIComponent(id)}/${action}`;
    const result = await api(path, { method: "POST", body: "{}" }, 120000);
    if (result.authority !== "PAPER_ONLY" || result.funded_authority !== false || result.order_submitted !== false) throw new Error("unsupported research authority");
    setHTML("research-control-result", `<p>${esc(t("researchControlDone"))}</p>`);
    await researchJobs();
  } catch (_) { setHTML("research-control-result", empty(t("researchControlError"))); }
  finally { state.researchBusy = false; if (state.researchState) renderResearchJobs(state.researchState); }
}

async function accountJournal() {
  const summary = $("account-state");
  try {
    const observation = await api("/api/account-observations");
    if (observation.state === "NOT_CONFIGURED") {
      summary.textContent = t("accountNotConfigured");
      setHTML("account-observations", `<p class="field-help">${esc(t("accountSetupHelp"))}</p>`);
      return;
    }
    if (observation.state !== "OBSERVED") throw new Error(t("accountError"));
    summary.textContent = `${t("accountObserved")} · ${observation.account_id || ""} · ${when(observation.observed_at)}`;
    setHTML("account-observations", `<h3>${esc(t("accountBalance"))}</h3><p class="field-help">${esc(t("accountBalanceNote"))}</p>${table([t("asset"), t("venueValue"), t("venueLocked")], list(observation.balances).map(row => [code(row.asset), amount(row.venue_value), amount(row.venue_locked)]), t("noBalances"))}
      <h3>${esc(t("accountOrders"))}</h3>${table([t("clientId"), t("pair"), t("rawStatus"), t("filledObserved"), t("settlement")], list(observation.orders).map(row => [code(row.client_id), code(row.symbol), esc(row.raw_status), amount(row.filled_observed), chip(t(row.settlement || "UNKNOWN"))]), t("noAccountOrders"))}
      <h3>${esc(t("accountExposure"))}</h3>${table([t("account"), t("product"), t("obligation"), t("status")], list(observation.exposure).map(row => [code(row.account_id), esc(row.raw_product || row.product), `${amount(row.obligation)} ${code(row.obligation_asset)}`, esc(row.status)]), t("noExposure"))}`);
  } catch (_) { summary.textContent = t("accountError"); setHTML("account-observations", ""); throw new Error(t("requestError")); }
}
async function externalJournal() {
  try {
    const data = await api("/api/external-order-events");
    setHTML("external-order-events", `<p class="field-help">${esc(t("externalNote"))}</p>${table([t("time"), t("account"), t("clientId"), t("rawStatus"), t("settlement")], list(data.events).slice(-100).reverse().map(row => [esc(when(row.observed_at)), code(row.account_id), code(row.client_id), esc(row.raw_status), chip(t(row.settlement || "UNKNOWN"))]), t("externalEmpty"))}`);
  } catch (_) { setHTML("external-order-events", empty(t("externalReadError"))); throw new Error(t("requestError")); }
}
async function offlineReviews() {
  try {
    const data = await api("/api/offline-ticket-reviews");
    setHTML("offline-review-events", table([t("previewHash"), t("state"), t("funded_authority"), t("actions")], list(data.tickets).slice(-100).reverse().map(row => [code(row.preview_sha256), esc(row.state), esc(t(row.funded_authority === true ? "yes" : "no")), row.state === "PREVIEWED" ? `<button class="button button-small" data-review-key="${esc(row.preview_sha256)}" data-decision="ACKNOWLEDGE">${esc(t("acknowledgeOffline"))}</button> <button class="button button-small" data-review-key="${esc(row.preview_sha256)}" data-decision="REJECT">${esc(t("rejectOffline"))}</button>` : ""]), t("offlineReviewEmpty")));
  } catch (_) { setHTML("offline-review-events", empty(t("offlineReviewReadError"))); throw new Error(t("requestError")); }
}
async function operate() {
  try {
    const safety = await api("/api/automation-safety");
    if (safety.mode !== "DISARMED" || safety.funded_authority !== false || safety.autopilot_enabled !== false || safety.executor_state_verified !== false
      || safety.protection !== "UNAVAILABLE" || safety.venue_stops !== "NOT_CERTIFIED" || safety.entries_enabled !== false) throw new Error("unsupported authority status");
    const fields = ["mode", "protection", "venue_stops", "entries_enabled", "autopilot_enabled", "funded_authority", "executor_state_verified", "source"];
    const html = keyValues(fields.map(key => [t(key), typeof safety[key] === "boolean" ? esc(t(safety[key] ? "yes" : "no")) : label(safety[key])]));
    setHTML("protection-state", html); setHTML("safety-status", html);
    setHTML("overview-safety", keyValues(["protection", "venue_stops", "funded_authority"].map(key => [t(key), typeof safety[key] === "boolean" ? esc(t("no")) : label(safety[key])])));
  } catch (_) {
    for (const id of ["protection-state", "safety-status", "overview-safety"]) setHTML(id, empty(t("protectionUnavailable")));
    throw new Error(t("requestError"));
  }
}

function renderOverview() {
  const markets = list(state.markets?.markets);
  setHTML("overview-summary", stat(t("observedPairs"), state.markets ? num(markets.length) : t("none"), t("observedPairsNote"))
    + stat(t("healthyQuotes"), state.markets ? num(markets.filter(healthyQuote).length) : t("none"), t("healthyQuotesNote"))
    + stat(t("savedRunCount"), state.runsLoaded ? num(state.runs.length) : t("none"), t("runCountNote"))
    + stat(t("executionStatus"), esc(t("disarmed")), t("stageExecuteHelp")));
  setHTML("overview-markets", state.markets ? table([t("pair"), t("bid"), t("ask"), t("spreadBps"), t("entry")], markets.slice(0, 5).map(m => [code(m.symbol), amount(m.bid), amount(m.ask), amount(m.spread_bps), eligibility(m.act?.entry)]), t("noMarkets")) : empty(t("loading")));
  const record = state.record, result = record?.result;
  setHTML("overview-research", result ? `<div class="run-heading"><h3>${code(result.symbol)}</h3>${chip(t(record.inputs?.store === "demo" ? "synthetic" : "paperOnly"))}</div>${curveFigure(result)}${keyValues([[t("net"), `${amount(result.end?.net)} ${code(result.quote)}`], [t("fills"), num(result.fills)]])}<p class="field-help">${esc(record.evidence?.primary_limitation || t("noCapital"))}</p>` : empty(t(state.runsLoaded ? "noRuns" : "loading"), t("noRunsHelp")));
  setHTML("overview-activity", state.runs.length ? table([t("pair"), t("time"), t("net")], state.runs.slice(0, 4).map(run => [code(run.inputs?.symbol), esc(when(run.inputs?.to)), amount(run.end?.net)])) : empty(t(state.runsLoaded ? "recentEvidenceEmpty" : "loading")));
}

const ticketFields = ["symbol", "side", "intent", "quantity", "bid", "ask", "worst_price", "fee_rate", "operator_quote_cap", "available_quote", "available_base", "minimum_quote", "observed_at", "expires_at", "snapshot_seq", "quote_age_ms"];
function renderTicketFields() {
  let values = {};
  try { values = JSON.parse($("offline-ticket").value || "{}"); } catch (_) { /* The JSON editor retains invalid text for correction. */ }
  if (!values || typeof values !== "object" || Array.isArray(values)) values = {};
  setHTML("ticket-fields", ticketFields.map(key => {
    const options = key === "side" ? ["BUY", "SELL"] : key === "intent" ? ["ENTRY", "EXIT"] : null;
    const value = values[key] ?? "";
    return `<label for="ticket-${key}">${esc(t(key))}${options
      ? `<select id="ticket-${key}" name="${key}" data-ticket-field="${key}"><option value="">${esc(t("none"))}</option>${options.map(option => `<option value="${option}"${value === option ? " selected" : ""}>${esc(t(option))}</option>`).join("")}</select>`
      : `<input class="input" id="ticket-${key}" name="${key}" data-ticket-field="${key}" value="${esc(value)}" dir="ltr" autocomplete="off" spellcheck="false"${["symbol", "observed_at", "expires_at"].includes(key) ? "" : ' inputmode="decimal"'}>`}</label>`;
  }).join(""));
}
let ticketRevision = 0;
let currentPreview = null;
function invalidateTicket() {
  ticketRevision++;
  currentPreview = null;
  $("offline-ticket").removeAttribute("aria-invalid");
  setHTML("ticket-output", `<p class="field-help">${esc(t("previewChanged"))}</p>`);
}
function editTicketField() {
  const payload = {};
  for (const field of $("ticket-fields").querySelectorAll("[data-ticket-field]")) {
    const key = field.dataset.ticketField, value = field.value;
    payload[key] = ["snapshot_seq", "quote_age_ms"].includes(key) && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : value;
  }
  $("offline-ticket").value = JSON.stringify(payload, null, 2);
  invalidateTicket();
}

function syntheticTicket() {
  const now = new Date();
  return { symbol: "BTCUSDT", side: "BUY", intent: "ENTRY", quantity: "0.01", bid: "100", ask: "101", worst_price: "103",
    fee_rate: "0.002", operator_quote_cap: "2", available_quote: "2", available_base: "0", minimum_quote: "1",
    observed_at: now.toISOString(), expires_at: new Date(now.getTime() + 30000).toISOString(), snapshot_seq: 1, quote_age_ms: 0 };
}
async function previewTicket() {
  const input = $("offline-ticket"), button = $("preview-ticket"), output = $("ticket-output");
  const raw = input.value, revision = ticketRevision;
  button.disabled = true; button.setAttribute("aria-busy", "true"); input.removeAttribute("aria-invalid");
  output.textContent = t("previewBusy"); rendered.delete("ticket-output");
  try {
    JSON.parse(raw);
    // Preserve duplicate fields so the backend's strict parser can reject ambiguity.
    const preview = await api("/api/dry-run/ticket", { method: "POST", body: raw });
    if (ticketRevision !== revision || input.value !== raw) return;
    if (preview.mode !== "DRY_RUN" || preview.funded_authority !== false || preview.order_submitted !== false) throw new Error("unsupported preview authority");
    currentPreview = preview;
    setHTML("ticket-output", `<div class="ticket-result"><h3>${esc(t("offlineTicketResult"))}</h3><p class="field-help">${esc(t("quoteFeeOnly"))}</p>${keyValues([
      [t("pair"), code(preview.symbol)], [t("quantity"), amount(preview.quantity)],
      [t("expectedGross"), amount(preview.estimated_gross_quote)], [t("worstGross"), amount(preview.worst_gross_quote)],
      [t("worstFee"), amount(preview.worst_fee_quote)], [t(preview.side === "SELL" ? "worstProceeds" : "worstSpend"), amount(preview.worst_total_quote)],
      [t("breakEven"), amount(preview.break_even_bid)], [t("effective"), `${esc(when(preview.observed_at))} → ${esc(when(preview.expires_at))}`],
    ])}<button type="button" class="button" id="save-preview">${esc(t("savePreview"))}</button>${disclosure(t("fullRecord"), preview, "ticket-preview")}</div>`);
  } catch (_) {
    if (ticketRevision !== revision || input.value !== raw) return;
    input.setAttribute("aria-invalid", "true");
    setHTML("ticket-output", `<p class="form-error" role="alert">${esc(t("offlineTicketError"))}</p>`);
  } finally { button.disabled = false; button.removeAttribute("aria-busy"); }
}

function renderRules(data) {
  $("rule-version").textContent = `${t("ruleVersion")} ${digits(data.version ?? "—")}`;
  const rules = list(data.rules), quarantined = list(data.quarantined);
  setHTML("rule-rows", (!rules.length && !quarantined.length ? `<section class="panel">${empty(t("rulesEmpty"), t("rulesEmptyHelp"))}</section>` : "")
    + rules.map(row => {
      const rule = row.body || {};
      return `<article class="panel rule-card"><div class="panel-heading"><div><h2 class="panel-title">${esc(rule.name || rule.id)}</h2><p class="field-help">${code(rule.id)} · ${code(rule.family)} · ${code(rule.action)}</p></div><div class="actions">${chip(t(row.state), row.state === "active" ? "ok" : "warn")}${row.state !== "disabled" ? `<button type="button" class="button button-small" data-disable="${esc(rule.id)}" data-focus="disable-${esc(rule.id)}"${state.savingRules ? " disabled" : ""}>${esc(t("disable"))}</button>` : ""}</div></div>
        ${rule.note ? `<p>${esc(rule.note)}</p>` : ""}${keyValues([[t("classification"), code(rule.class)], [t("status"), label(rule.status)], [t("source"), esc(rule.source)], [t("effective"), `${esc(when(rule.effective_from))} → ${rule.effective_until ? esc(when(rule.effective_until)) : "∞"}`], [t("blocksNow"), list(row.blocks_now).length ? row.blocks_now.map(code).join(", ") : esc(t("nothing"))]])}
        ${disclosure(t("history"), { rule, history: row.history || [] }, "rule-" + rule.id)}</article>`;
    }).join("") + quarantined.map(row => `<article class="panel rule-card"><div class="panel-heading"><h2 class="panel-title">${code(row.id)}</h2>${chip(t("quarantineNote"), "bad")}</div><p>${esc(row.error)}</p>${disclosure(t("fullRecord"), row.body || row, "quarantine-" + row.id)}</article>`).join(""));
}
async function rules() { state.rules = await api("/api/rules"); renderRules(state.rules); }
async function changeRule(button, action) {
  if (state.savingRules) return;
  state.savingRules = true; button.disabled = true; button.setAttribute("aria-busy", "true");
  try { await action(); await rules(); }
  catch (_) { $("rule-action-result").textContent = t("ruleWriteError"); }
  finally { state.savingRules = false; button.disabled = false; button.removeAttribute("aria-busy"); if (state.rules) renderRules(state.rules); }
}

function renderHealth(data) {
  setHTML("health-summary", stat(t("connected"), esc(t(data.connected ? "connectedValue" : "disconnectedValue")), t(data.demo ? "synthetic" : "liveData"))
    + stat(t("frameAge"), data.last_frame_age_s == null ? t("unknown") : `${num(data.last_frame_age_s)} <small>${esc(t("seconds"))}</small>`)
    + stat(t("reconnects"), num(data.reconnects)));
  const events = [...(data.fatal ? [data.fatal] : []), ...list(data.errors)];
  setHTML("health-errors", events.length ? `<ul class="event-list">${events.map(event => `<li>${typeof event === "string" ? esc(event) : json(event)}</li>`).join("")}</ul>` : empty(t("noCollectorEvents")));
  setHTML("health-quality", table([t("time"), t("instrument"), t("flag"), t("detail")], list(data.quality).map(row => [esc(when(row.ts)), code(row.instrument), label(row.flag), esc(row.detail)]), t("noQualityEvents")));
  const readiness = data.readiness;
  setHTML("health-readiness", `<h2 class="panel-title">${esc(t("publicReadiness"))}</h2><p class="field-help">${esc(t("publicReadinessNote"))}</p><p>${label(readiness?.status)}</p>${table([t("pair"), t("status"), t("bidAge"), t("askAge")], list(readiness?.markets).map(row => [code(row.symbol), label(row.state), num(row.bid_age_seconds), num(row.ask_age_seconds)]), t("unavailable"))}`);
}
async function venueFacts() {
  try {
    const report = await api("/api/venue-facts");
    if (report.state === "NOT_CONFIGURED") { setHTML("venue-facts", empty(t("venueFactsEmpty"))); return; }
    setHTML("venue-facts", `<p class="field-help">${esc(t("venueFactsInfo"))}</p>${table([t("capability"), t("state")], Object.entries(report.capabilities || {}).map(([name, value]) => [esc(name), label(value.state)]))}
      ${table([t("time"), t("status"), t("source"), t("evidenceId")], list(report.facts).slice(0, 20).map(fact => [esc(when(fact.observed_at)), `${esc(fact.kind)} · ${esc(fact.state)}`, esc(fact.source), code(fact.evidence_id)]))}`);
  } catch (_) { setHTML("venue-facts", empty(t("venueFactsError"))); throw new Error(t("requestError")); }
}
async function chaos() {
  try {
    const report = await api("/api/chaos-report");
    if (report.state === "NOT_RUN") { setHTML("chaos-report", empty(t("chaosNotRun"))); return; }
    setHTML("chaos-report", `<p>${chip(t(report.passed === true ? "simulationPassed" : "simulationFailed"), report.passed === true ? "ok" : "bad")}</p><p class="field-help">${esc(t("chaosNote"))}</p>${table([t("fixture"), t("runs"), t("settled"), t("frozen"), t("violations")], list(report.fixtures).map(fixture => [esc(fixture.fixture), num(fixture.runs), num(fixture.settled), num(fixture.frozen), num(fixture.violations)]))}
      ${disclosure(t("exampleTrace"), { seeds_per_fixture: report.seeds_per_fixture, total_violations: report.total_violations, funded_authority: report.funded_authority, examples: list(report.fixtures).map(fixture => ({ fixture: fixture.fixture, incidents: fixture.incidents, example: fixture.example })) }, "chaos-examples")}`);
  } catch (_) { setHTML("chaos-report", empty(t("chaosError"))); throw new Error(t("requestError")); }
}

function renderFeed() {
  const health = state.health;
  const key = state.apiError ? "refreshFailed" : !health ? "feedUnknown" : health.fatal ? "feedStopped" : health.connected ? "feedConnected" : "feedDisconnected";
  setHTML("feed-status", `<span class="dot${state.apiError || health?.fatal || health?.connected === false ? " dot-warn" : ""}" aria-hidden="true"></span><span>${esc(t(key))}</span>`);
  $("connection-error").hidden = !state.apiError;
}
function updateClock() {
  const now = new Date();
  $("clock").textContent = new Intl.DateTimeFormat(lang === "fa" ? "fa-IR" : "en-GB", { timeZone: "Asia/Tehran", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(now) + " · " + (lang === "fa" ? "تهران" : "Tehran");
  $("clock").setAttribute("datetime", now.toISOString());
}
let pollTimer, refreshTask, refreshAgain = false;
async function collectView(name, healthTask) {
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
async function refresh() {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  if (refreshTask) { refreshAgain = true; return refreshTask; }
  const name = state.view;
  updateClock();
  refreshTask = (async () => {
    const healthTask = api("/api/health").then(data => { state.health = data; return data; });
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
function selectSavedRun(event) {
  const button = event.target.closest?.("[data-run]") || event.target;
  if (!button.dataset.run) return;
  state.selectedRun = button.dataset.run; state.record = null;
  renderRunList(); refresh();
}
$("run-list").addEventListener("click", selectSavedRun);
$("run-detail").addEventListener("click", async event => {
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
$("language-toggle").onclick = () => { lang = lang === "en" ? "fa" : "en"; remember("lang", lang); applyLang(); refresh(); };
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
window.addEventListener?.("hashchange", () => {
  const name = location.hash.slice(1);
  if (!name || Object.hasOwn(viewKeys, name)) showView(name, true);
});
document.addEventListener("visibilitychange", () => { clearTimeout(pollTimer); if (!document.hidden) refresh(); });
$("demo-banner").hidden = !DEMO;
applyLang();
showView(location.hash.slice(1));
