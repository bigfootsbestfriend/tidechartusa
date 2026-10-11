// Station page extras that need fresh data or the browser:
// - National Weather Service marine forecast and active warnings for the station's marine zone
// - NOAA live water temperature, and the measured water level compared with the prediction
// - "Print this tide table" and "Add tides to my calendar" (.ics built from the page's own data)
// Every fetch is optional: if one fails, that line keeps its fallback text and link.
(() => {
  const data = JSON.parse((document.getElementById("tide-data") || {}).textContent || "null");
  const live = document.getElementById("live");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const getJSON = (url, accept) =>
    fetch(url, accept ? { headers: { Accept: accept } } : {}).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
  const NWS = "application/geo+json";
  const COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?application=tidechartusa&format=json&units=english";
  const ago = (iso) => {
    const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
  };

  // Predicted height at a time, same cosine curve as the chart.
  const predicted = (t) => {
    const ev = data && data.ev;
    if (!ev) return null;
    for (let i = 0; i < ev.length - 1; i++) {
      const [ta, va] = ev[i], [tb, vb] = ev[i + 1];
      if (ta <= t && t <= tb) return va + (vb - va) * (1 - Math.cos(Math.PI * (t - ta) / (tb - ta))) / 2;
    }
    return null;
  };

  // NWS zone codes in a forecast block header: "PZZ530-531-111015-" or "ANZ330>335-...".
  const zonesIn = (header) => {
    const out = new Set();
    let prefix = "";
    for (const tok of header.replace(/\s+/g, "").split("-")) {
      if (/^\d{6}$/.test(tok)) break;
      const m = tok.match(/^([A-Z]{2}[ZC])?(\d{3})(?:>(\d{3}))?$/);
      if (!m) continue;
      if (m[1]) prefix = m[1];
      const a = +m[2], b = m[3] ? +m[3] : a;
      for (let n = a; n <= b; n++) out.add(prefix + String(n).padStart(3, "0"));
    }
    return out;
  };

  const forecastFor = (text, zone) => {
    for (const block of text.split("$$")) {
      const m = block.match(/^\s*((?:[A-Z]{2}[ZC]\d{3}[\d>\-\s]*?-)+\s*\d{6}-)/m);
      if (!m || !zonesIn(m[1]).has(zone)) continue;
      const body = block.slice(block.indexOf(m[1]) + m[1].length).trim();
      const lines = body.split("\n");
      // Skip the zone name lines (up to the issue time) and keep headlines + periods.
      const at = lines.findIndex((l) => /\d{3,4} (AM|PM) [A-Z]{3,4} /.test(l));
      const issued = at >= 0 ? lines[at].trim() : "";
      const rest = lines.slice(at + 1).join("\n").trim();
      const heads = [...rest.matchAll(/\.\.\.([^.]+?)\.\.\./g)].map((x) => x[1].trim());
      const periods = [...rest.matchAll(/^\.([A-Z][A-Z .']+?)\.\.\.([\s\S]*?)(?=^\.[A-Z]|$(?![\s\S]))/gm)]
        .map((x) => [x[1].toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()), x[2].replace(/\s+/g, " ").trim()]);
      return { issued, heads, periods };
    }
    return null;
  };

  const loadForecast = async (zone, office) => {
    const box = document.getElementById("lv-fc");
    for (const type of ["CWF", "NSH", "OFF"]) {
      try {
        const list = await getJSON(`https://api.weather.gov/products/types/${type}/locations/${office}`, NWS);
        const id = list["@graph"] && list["@graph"][0] && list["@graph"][0].id;
        if (!id) continue;
        const prod = await getJSON(`https://api.weather.gov/products/${id}`, NWS);
        const fc = forecastFor(prod.productText || "", zone);
        if (!fc || !fc.periods.length) continue;
        box.innerHTML =
          fc.heads.map((h) => `<p class="adv">${esc(h)}</p>`).join("") +
          `<dl class="fc">${fc.periods.slice(0, 6).map(([p, t]) => `<dt>${esc(p)}</dt><dd>${esc(t)}</dd>`).join("")}</dl>` +
          `<p class="note">Issued ${esc(fc.issued)} by the National Weather Service. ` +
          `<a href="https://marine.weather.gov/MapClick.php?zoneid=${esc(zone)}">Full forecast</a></p>`;
        return;
      } catch (e) { /* try the next product type */ }
    }
  };

  // Active NWS alerts for the station's marine zone and its exact point (coastal flood, high surf and other
  // land-side alerts), shown as a banner at the top of the page, most serious first.
  const SEV = { Extreme: 0, Severe: 1, Moderate: 2, Minor: 3, Unknown: 4 };
  const kind = (ev) => /warning/i.test(ev) ? "warning" : /watch/i.test(ev) ? "watch" : /advisory/i.test(ev) ? "advisory" : "statement";
  // NWS headlines are in capitals: make them a sentence, keeping AM/PM, time zones and day names right.
  const sentence = (t) => String(t).toLowerCase().replace(/^./, (c) => c.toUpperCase())
    .replace(/\b(am|pm|[acemph]k?[sd]t|hst|nws)\b/g, (w) => w.toUpperCase())
    .replace(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b/g,
      (w) => w[0].toUpperCase() + w.slice(1));
  const loadAlerts = async (zone, lat, lng) => {
    const box = document.getElementById("alerts");
    if (!box) return;
    const icon = (n) => { const t = box.querySelector(`template.i-${n}`); return t ? t.innerHTML : ""; };
    const urls = [`https://api.weather.gov/alerts/active?point=${lat},${lng}`];
    if (zone) urls.push(`https://api.weather.gov/alerts/active?zone=${zone}`);
    const got = await Promise.all(urls.map((u) => getJSON(u, NWS).catch(() => null)));
    if (got.every((g) => g === null)) return; // couldn't check: show nothing rather than a false all-clear
    const seen = new Set();
    const alerts = got.flatMap((g) => (g && g.features) || []).map((f) => f.properties)
      .filter((p) => p.status === "Actual" && p.messageType !== "Cancel" && !seen.has(p.event) && seen.add(p.event))
      .sort((a, b) => (SEV[a.severity] ?? 4) - (SEV[b.severity] ?? 4));
    const tpl = box.querySelectorAll("template");
    const until = (p) => {
      const e = p.ends || p.expires;
      return e ? ` until ${new Date(e).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}` : "";
    };
    const sign = document.getElementById("emails") ? ` <a href="#emails">Get alerts for this spot by email</a>` : "";
    box.innerHTML = alerts.length
      ? alerts.map((p) => `<details class="al ${kind(p.event)}"><summary>${icon("warn")}<span><b>${esc(p.event)}</b>${esc(until(p))}` +
          `${p.parameters && p.parameters.NWSheadline ? `<small>${esc(sentence(p.parameters.NWSheadline[0]))}</small>` : ""}</span></summary>` +
          `<div class="al-body">${esc((p.description || "").trim()).replace(/\* ([A-Z ]+)\.\.\./g, (m, k) => `<b>${k[0] + k.slice(1).toLowerCase()}:</b> `).replace(/\n\n/g, "<br><br>")}` +
          `${p.instruction ? `<p><b>What to do:</b> ${esc(p.instruction)}</p>` : ""}<p class="note">${esc(p.areaDesc || "")} · National Weather Service</p></div></details>`).join("") +
        `<p class="al-foot">Tap an alert for details.${sign}</p>`
      : `<p class="al-clear">${icon("check")}No weather warnings or advisories here right now.${sign}</p>`;
    tpl.forEach((t) => box.appendChild(t));
    box.hidden = false;
  };

  const loadWaterTemp = async (st) => {
    try {
      const j = await getJSON(`${COOPS}&product=water_temperature&date=latest&time_zone=gmt&station=${st}`);
      const d = j.data && j.data[0];
      if (!d || d.v === "") return;
      document.querySelector("#lv-wt span").textContent = `${(+d.v).toFixed(1)} °F (${ago(d.t.replace(" ", "T") + "Z")})`;
    } catch (e) { document.getElementById("lv-wt").hidden = true; }
  };

  const loadWaterLevel = async (st) => {
    try {
      const j = await getJSON(`${COOPS}&product=water_level&date=latest&datum=MLLW&time_zone=gmt&station=${st}`);
      const d = j.data && j.data[0];
      if (!d || d.v === "") return;
      const t = Date.parse(d.t.replace(" ", "T") + "Z") / 1000;
      const obs = +d.v, pred = predicted(t);
      let txt = `${obs.toFixed(1)} ft (${ago(d.t.replace(" ", "T") + "Z")})`;
      if (pred !== null) {
        const diff = obs - pred;
        txt += Math.abs(diff) < 0.15 ? ", right on the prediction"
          : `, ${Math.abs(diff).toFixed(1)} ft ${diff > 0 ? "above" : "below"} the prediction`;
      }
      document.querySelector("#lv-wl span").textContent = txt;
    } catch (e) { document.getElementById("lv-wl").hidden = true; }
  };

  // Land forecast for the station's point.
  const loadWeather = async (lat, lng) => {
    const box = document.getElementById("lv-wx");
    try {
      // Stations out on the water have no forecast point: try a few spots nearby (about 3 miles away).
      let pt = null, fc = null;
      for (const [dy, dx] of [[0, 0], [0.04, 0], [-0.04, 0], [0, 0.05], [0, -0.05], [0.04, 0.05], [-0.04, -0.05]]) {
        pt = await getJSON(`https://api.weather.gov/points/${(+lat + dy).toFixed(4)},${(+lng + dx).toFixed(4)}`, NWS).catch(() => null);
        fc = pt && pt.properties && pt.properties.forecast ? await getJSON(pt.properties.forecast, NWS).catch(() => null) : null;
        if (fc && fc.properties && (fc.properties.periods || []).length) break;
      }
      if (!fc || !fc.properties) return;
      window.tcWx = fc.properties.periods || [];
      window.dispatchEvent(new Event("tc:wx")); // the trip planner uses the wind forecast
      const periods = window.tcWx.slice(0, 4);
      if (!periods.length) return;
      box.innerHTML = `<div class="wx">${periods.map((q) => `<div class="wx-p">
        ${q.icon ? `<img src="${esc(q.icon.replace("size=medium", "size=large"))}" alt="" width="56" height="56" loading="lazy">` : ""}
        <b>${esc(q.name)}</b><span class="t">${q.temperature}°${esc(q.temperatureUnit)}</span>
        <span>${esc(q.shortForecast)}</span><span class="w">Wind ${esc(q.windDirection)} ${esc(q.windSpeed)}</span></div>`).join("")}</div>
        <p class="note">National Weather Service forecast for the nearest land point.
        <a href="https://forecast.weather.gov/MapClick.php?lat=${lat}&lon=${lng}">7-day and hourly</a></p>`;
    } catch (e) { /* keep the weather.gov link */ }
  };

  if (live) {
    const { st, zone, office, wt, wl, lat, lng } = live.dataset;
    if (lat && lng) loadWeather(lat, lng);
    if (zone && office) loadForecast(zone, office);
    loadAlerts(zone, lat, lng);
    if (wt === "1") loadWaterTemp(st);
    if (wl === "1") loadWaterLevel(st);
  }

  // Print just the month table (print CSS hides the rest).
  document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));

  // Calendar file with every high and low on the page.
  document.querySelectorAll("[data-ics]").forEach((b) => b.addEventListener("click", () => {
    if (!data) return;
    const stamp = (t) => new Date(t * 1000).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tide Chart USA//EN", "CALSCALE:GREGORIAN",
      `X-WR-CALNAME:Tides: ${data.name}`];
    const now = stamp(Date.now() / 1000);
    for (const [t, v, k] of data.ev) {
      if (t < Date.now() / 1000 - 86400) continue;
      lines.push("BEGIN:VEVENT", `UID:${data.id}-${t}@tidechartusa.com`, `DTSTAMP:${now}`,
        `DTSTART:${stamp(t)}`, `DTEND:${stamp(t + 900)}`,
        `SUMMARY:${k === "H" ? "High" : "Low"} tide ${v.toFixed(1)} ft`,
        `DESCRIPTION:${data.name} (NOAA ${data.id}). Predicted\\, not observed. Not for navigation.`, "END:VEVENT");
    }
    lines.push("END:VCALENDAR");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/calendar" }));
    a.download = `tides-${data.id}.ics`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }));
})();
