// Native ES module for desktop operator alerts (F13 + F15 incremental ES-module migration).
// Emits each authorized condition once until it clears, including feed disconnect and API unreachable states.

export function createAlertMonitor({ getEl, translate, getSaved, setSaved, fetchApi }) {
  let alertsOn = getSaved("alerts", "off", ["on", "off"]) === "on";
  const alerted = new Set();

  function checkAlerts(health) {
    if (!alertsOn || typeof Notification === "undefined" || Notification.permission !== "granted" || !health) return;
    const active = [
      ...(health.storage?.hours_to_floor != null && health.storage.hours_to_floor < 24 ? [["disk", translate("alertDisk")]] : []),
      ...(health.connected === false ? [["disconnected", translate("alertDisconnected") || "Market feed disconnected."]] : []),
      ...(health.connected && health.last_frame_age_s > 120 ? [["stall", translate("alertStall")]] : []),
      ...(health.clock_paused ? [["clock", translate("alertClock")]] : []),
      ...(health.integrity?.mismatched ? [["integrity", translate("alertIntegrity")]] : []),
      ...(health.fatal ? [["fatal", String(health.fatal)]] : []),
    ];
    for (const [key, body] of active) {
      if (!alerted.has(key)) {
        alerted.add(key);
        new Notification("TradingGYM", { body, tag: key });
      }
    }
    for (const key of [...alerted]) {
      if (!active.some(([name]) => name === key)) alerted.delete(key);
    }
  }

  function reportAlertPollFailure() {
    if (!alertsOn || typeof Notification === "undefined" || Notification.permission !== "granted") return;
    if (!alerted.has("unreachable")) {
      alerted.add("unreachable");
      new Notification("TradingGYM", {
        body: translate("alertUnreachable") || "Local TradingGYM API unreachable.",
        tag: "unreachable",
      });
    }
  }

  function renderAlertToggle() {
    const btn = getEl("alerts-toggle");
    if (!btn) return;
    btn.textContent = translate(alertsOn ? "alertsOn" : "alertsOff");
    btn.setAttribute("aria-pressed", String(alertsOn));
  }

  function mount() {
    const btn = getEl("alerts-toggle");
    if (btn) {
      btn.addEventListener("click", async () => {
        if (!alertsOn && typeof Notification !== "undefined" && Notification.permission !== "granted") {
          await Notification.requestPermission();
        }
        alertsOn = !alertsOn && typeof Notification !== "undefined" && Notification.permission === "granted";
        setSaved("alerts", alertsOn ? "on" : "off");
        renderAlertToggle();
      });
    }
    renderAlertToggle();
    // The page stops refreshing while hidden; alerts still need a slow health check.
    setInterval(() => {
      if (document.hidden && alertsOn) fetchApi("/api/health").then(checkAlerts, reportAlertPollFailure);
    }, 60000);
  }

  return { checkAlerts, reportAlertPollFailure, renderAlertToggle, mount };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const monitor = createAlertMonitor({
    getEl: id => document.getElementById(id),
    translate: key => (typeof window.t === "function" ? window.t(key) : key),
    getSaved: (k, fb, allowed) => (typeof window.saved === "function" ? window.saved(k, fb, allowed) : fb),
    setSaved: (k, v) => { if (typeof window.remember === "function") window.remember(k, v); },
    fetchApi: path => (typeof window.api === "function" ? window.api(path) : Promise.reject(new Error("api unavailable"))),
  });
  // Explicit read-only bridge for legacy classic scripts during incremental ES-module migration.
  window.checkAlerts = monitor.checkAlerts;
  window.reportAlertPollFailure = monitor.reportAlertPollFailure;
  window.renderAlertToggle = monitor.renderAlertToggle;
  monitor.mount();
}
