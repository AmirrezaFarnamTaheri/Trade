// Desktop notifications for conditions that need the operator, once per condition until it clears.
let alertsOn = saved("alerts", "off", ["on", "off"]) === "on";
const alerted = new Set();
/** Emit each authorized operator alert once until the condition clears. */
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
/** Keep the notification toggle label and pressed state synchronized. */
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
