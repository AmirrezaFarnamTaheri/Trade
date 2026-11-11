"use strict";
// Market catalogue, observations and rule eligibility.
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
    [t("source"), esc(rule.source)], [t("confirmed"), stampHtml(rule.confirmed)],
  ])}</li>`;
}
function verdictDetails(title, verdict) {
  if (!verdict) return `<section><h3>${esc(title)}</h3>${empty(t("notEvaluated"))}</section>`;
  return `<section><h3>${esc(title)} ${eligibility(verdict)}</h3><h4>${esc(t("blockers"))}</h4>${list(verdict.blockers).length
    ? `<ul class="rule-references">${list(verdict.blockers).map(ruleReference).join("")}</ul>` : `<p class="muted">${esc(t("noBlockers"))}</p>`}
    ${list(verdict.warnings).length ? `<h4>${esc(t("warnings"))}</h4><ul class="rule-references">${verdict.warnings.map(ruleReference).join("")}</ul>` : ""}
    ${keyValues([[t("nextRuleChange"), verdict.next_change ? stampHtml(verdict.next_change) : esc(t("noRuleChange"))],
      [t("quotaRemaining"), amount(verdict.quota_remaining)], [t("ruleVersion"), num(verdict.ruleset_version)]])}
    <p class="field-help">${esc(t("changeNote"))}</p></section>`;
}
function renderMarkets() {
  const data = state.markets;
  if (!data) return;
  const markets = list(data.markets), search = state.filter.trim().toLocaleLowerCase();
  const caps = data.capabilities;
  setHTML("market-capabilities", caps ? keyValues([
    [t("catalogSource"), label(caps.catalog_source || "UNKNOWN")],
    [t("collectionMode"), label(caps.collection?.mode) + (caps.collection?.requested_assets != null ? ` · ${num(caps.collection.requested_assets)}` : "")],
    [t("listedPairs"), num(caps.catalog_markets)],
    [t("collectionCapacity"), num(caps.asset_capacity)],
    [t("paperSides"), esc(t("paperSidesNote"))],
    [t("financingScope"), esc(t("financingScopeNote"))],
    [t("decisionTimeframes"), list(caps.resolutions).map(code).join(" · ")],
    [t("candleFetchTimeframes"), list(caps.venue_candle_fetch_resolutions).map(code).join(" · ")],
  ]) + `<p class="field-help">${esc(t("timeframeSourceNote"))}</p>` : empty(t("unavailable")));
  const catalogue = list(data.catalog).filter(row => (!state.quote || row.quote === state.quote)
    && (!search || [row.symbol, row.base, row.quote].some(value => String(value ?? "").toLocaleLowerCase().includes(search))));
  setHTML("market-catalogue", table([t("pair"), t("collectionState"), t("riskFlag")], catalogue.map(row => [
    code(row.symbol), label(row.reason), esc(t(row.risk_flagged ? "yes" : "no")),
  ]), t("nothing")));
  const quality = $("market-quality").value || "all", sort = $("market-sort").value || "symbol";
  const shown = markets.filter(market => (!state.quote || market.quote === state.quote)
    && (quality === "all" || (quality === "healthy" ? healthyQuote(market) : quality === "missing" ? !market.bid || !market.ask
      : quality === "stale" ? list(market.flags).includes("STALE") : quality === "eligible" ? market.act?.entry?.allowed === true : market.act?.entry?.allowed === false))
    && (!search || [market.symbol, market.base, market.quote, ...Object.values(market.names || {})].some(value => String(value ?? "").toLocaleLowerCase().includes(search))));
  shown.sort((a, b) => {
    const field = sort === "age" ? "book_age_s" : "spread_bps";
    if (sort !== "symbol") {
      const av = a[field] == null ? null : Number(a[field]), bv = b[field] == null ? null : Number(b[field]);
      if (av == null || !Number.isFinite(av)) return bv == null || !Number.isFinite(bv) ? a.symbol.localeCompare(b.symbol) : 1;
      if (bv == null || !Number.isFinite(bv)) return -1;
      if (av !== bv) return sort === "age" ? bv - av : av - bv;
    }
    return a.symbol.localeCompare(b.symbol);
  });
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
      <td class="num">${trade ? `${amount(trade.price)}<span class="sub">${amount(trade.qty)} ${code(market.base)} · ${stampHtml(trade.ts)}</span>` : t("none")}</td>
      <td>${quality}${market.book_age_s != null ? `<span class="sub">${num(market.book_age_s)} ${esc(t("seconds"))}</span>` : ""}</td>
      <td>${eligibility(market.act?.entry)}${market.data_quality?.grade === "POOR" ? ` ${chip(t("poorData"), "warn")}` : ""}</td><td>${eligibility(market.act?.exit)}</td></tr>
      ${expanded ? `<tr class="market-detail-row"><td colspan="8"><section class="market-detail" id="${esc(id)}" aria-label="${esc(t("pairDetails") + " " + market.symbol)}">
        ${keyValues([[t("bestBidQuantity"), `${amount(market.bid_qty)} ${code(market.base)}`], [t("bestAskQuantity"), `${amount(market.ask_qty)} ${code(market.base)}`],
          [t("absoluteSpread"), `${amount(market.spread)} ${code(market.quote)}`], ...(market.unit ? [[t("unitEpoch"), `${code(market.unit.code)} · ${num(market.unit.epoch)}`]] : [])])}
        <h3>${esc(t("observedDepth"))}</h3><p class="field-help">${esc(t("depthNote"))}</p>${market.liquidity?.status === "AVAILABLE" ? table([t("depthBand"), `${t("bidDepth")} · ${market.base}`, `${t("askDepth")} · ${market.base}`, t("imbalance")], market.liquidity.bands.map(band => [num(band.width_bps), amount(band.bid_base), amount(band.ask_base), amount(band.imbalance)])) : empty(t("unavailable"))}
        <div class="detail-grid">${verdictDetails(t("entry"), market.act?.entry)}${verdictDetails(t("exit"), market.act?.exit)}</div></section></td></tr>` : ""}`;
  }).join(""));
}

