$("language-toggle").onclick = () => { lang = lang === "en" ? "fa" : "en"; remember("lang", lang); applyLang(); renderAlertToggle(); refresh(); };
$("zone-toggle").onclick = () => { zone = zone === "UTC" ? "Asia/Tehran" : "UTC"; remember("zone", zone); applyLang(); };
$("theme-toggle").onclick = () => { theme = theme === "light" ? "dark" : "light"; remember("theme", theme); applyLang(); };
$("refresh-data").onclick = () => refresh();
$("retry").onclick = () => refresh();

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
