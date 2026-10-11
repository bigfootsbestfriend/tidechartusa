// Fishing forecast card on station pages. The page carries an hour-by-hour bite score for the week (built
// from tides, solunar periods, light and moon phase, see bite_days() in site/build.py). This script:
// - switches days and marks the current hour,
// - folds in the National Weather Service hourly wind, gusts and rain chance, and the pressure trend from
//   the nearest weather station (falling pressure before a front often means a feeding spree),
// - explains the score ("why") and the hour you tap,
// - adds the nearest NWS radar loop.
// Everything live is optional: without it the card keeps the tide-and-moon forecast.
(() => {
  const el = document.getElementById("tide-data"), card = document.getElementById("bite");
  if (!el || !card) return;
  const data = JSON.parse(el.textContent);
  if (!data.bite) return;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const band = (s) => (s >= 75 ? 4 : s >= 55 ? 3 : s >= 35 ? 2 : 1);
  const LABEL = ["", "Slow", "Fair", "Good", "Excellent"];
  const now = Date.now() / 1000;
  const isoToday = Object.keys(data.days).find((k) => data.days[k][0] <= now && now < data.days[k][1]);
  let iso = data.bite[isoToday] ? isoToday : Object.keys(data.bite)[0];
  const t0 = () => data.days[iso][0];
  const clock = (t) => {
    let m = Math.round((t - t0()) / 60);
    m = ((m % 1440) + 1440) % 1440;
    const h = Math.floor(m / 60);
    return `${h % 12 || 12}:${String(m % 60).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  };
  const hourLabel = (n) => { const h = n % 24; return `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`; };

  // Tide movement at a time (0 slack .. 1 strong), same cosine curve as the chart.
  const ev = data.ev;
  const rates = [];
  for (let i = 1; i < ev.length; i++) rates.push(Math.abs(ev[i][1] - ev[i - 1][1]) * Math.PI / 2 / ((ev[i][0] - ev[i - 1][0]) / 3600));
  rates.sort((a, b) => a - b);
  const maxRate = rates[Math.floor(rates.length * 0.8)] || 1;
  const movement = (t) => {
    for (let i = 0; i + 1 < ev.length; i++) {
      const [ta, ha] = ev[i], [tb, hb] = ev[i + 1];
      if (ta <= t && t <= tb) return {
        mv: Math.min(1, Math.abs(hb - ha) * Math.PI / 2 * Math.sin(Math.PI * (t - ta) / (tb - ta)) / ((tb - ta) / 3600) / maxRate),
        rising: hb > ha, next: [tb, hb > ha ? "high" : "low"],
      };
    }
    return null;
  };

  // Live weather by epoch hour: {wind, gust, dir, pop}; pressure {hpa, trend (hPa per 3h)}.
  const wx = {};
  let pressure = null;
  const adjusted = (d) => {
    const [, hrs] = data.bite[d];
    const start = data.days[d][0];
    return hrs.map((s, n) => {
      const t = start + n * 3600 + 1800, w = wx[Math.floor(t / 3600)];
      if (w && w.wind >= 15) s -= Math.min(14, (w.wind - 12) * 1.5);
      if (w && w.gust >= 25) s -= 4;
      if (pressure && d === isoToday && t >= now - 3600 && t < now + 8 * 3600) {
        const tr = pressure.trend;
        s += tr <= -1 && tr > -4 ? 6 : tr <= -4 ? 1 : tr >= 2 ? -5 : 2;
      }
      return Math.max(3, Math.min(98, Math.round(s)));
    });
  };
  const windowsOf = (d, hrs) => {
    const start = data.days[d][0], cut = Math.max(Math.max(...hrs) - 12, 40), out = [];
    let run = null;
    hrs.forEach((s, n) => {
      const t = start + n * 3600;
      if (s >= cut) run = run ? [run[0], t + 3600, Math.max(run[2], s)] : [t, t + 3600, s];
      else if (run) { out.push(run); run = null; }
    });
    if (run) out.push(run);
    return out.sort((a, b) => b[2] - a[2]).slice(0, 2);
  };

  const factorsHtml = (d, hrs) => {
    const out = [];
    const isNow = d === isoToday;
    const t = isNow ? now : data.days[d][0] + 12 * 3600;
    const m = movement(t);
    if (m) out.push(["current", m.mv > 0.66 ? "Strong tide flow" : m.mv > 0.33 ? "Moderate tide flow" : "Near slack water",
      `${isNow ? "Now" : "At noon"} the water is ${m.rising ? "rising" : "falling"}; next ${m.next[1]} tide at ${clock(m.next[0])}. Moving water stirs up bait.`, m.mv > 0.33]);
    const why = $("bite-why");
    if (why && why.dataset.moon === undefined) why.dataset.moon = why.textContent;
    out.push(["moon", why ? why.dataset.moon : "Moon", "Days near the new and full moon bring bigger tides and usually a stronger bite.", null]);
    const ws = hrs.map((_, n) => wx[Math.floor((data.days[d][0] + n * 3600 + 1800) / 3600)]).filter(Boolean);
    if (ws.length) {
      const cur = isNow ? wx[Math.floor(now / 3600)] || ws[0] : ws.reduce((a, b) => (b.wind > a.wind ? b : a));
      const calm = ws.filter((w) => w.wind < 10).length;
      out.push(["wind", `Wind ${cur.dir || ""} ${Math.round(cur.wind)} mph${cur.gust ? `, gusts ${Math.round(cur.gust)}` : ""}${isNow ? " now" : " at the windiest"}`,
        cur.wind < 10 ? "Light wind: easy casting and boat control." : cur.wind < 18 ? "Breezy: fish the sheltered side." : "Windy: rough water, pick protected spots.",
        cur.wind < 15, calm ? `${calm} calm hour${calm === 1 ? "" : "s"} (under 10 mph) on this day.` : ""]);
      const wet = ws.filter((w) => w.pop >= 50).length;
      if (wet) out.push(["rain", `Rain likely for about ${wet} hour${wet === 1 ? "" : "s"}`, "Light rain can help the bite; lightning means get off the water.", null]);
    }
    if (pressure && isNow) {
      const tr = pressure.trend;
      out.push(["gauge", `Pressure ${(pressure.hpa * 0.02953).toFixed(2)} inHg, ${tr <= -1 ? "falling" : tr >= 2 ? "rising fast" : tr >= 1 ? "rising" : "steady"}`,
        tr <= -1 ? "Slowly falling pressure often brings a feeding spree before a front." : tr >= 2 ? "Rising fast after a front: fish often go quiet." : tr >= 1 ? "Slowly rising: often a steady but slower bite." : "Stable pressure: a normal bite.",
        tr <= -1 && tr > -4]);
    }
    return out.map(([k, a, b, good, extra]) => `<li class="${good === true ? "good" : good === false ? "bad" : ""}" data-k="${k}"><b>${esc(a)}</b><span>${esc(b)}${extra ? " " + esc(extra) : ""}</span></li>`).join("");
  };

  const render = () => {
    const hrs = adjusted(iso);
    const top = [...hrs].sort((a, b) => b - a).slice(0, 3);
    const base = data.bite[iso][0], rawTop = [...data.bite[iso][1]].sort((a, b) => b - a).slice(0, 3);
    // Shift the day score by how much the weather moved its best hours.
    const score = Math.max(5, Math.min(98, Math.round(base + (top.reduce((a, b) => a + b, 0) - rawTop.reduce((a, b) => a + b, 0)) / 3)));
    $("bite-score").textContent = score;
    $("bite-label").textContent = LABEL[band(score)];
    $("bite-ring").className = `bite-ring b${band(score)}`;
    const wins = windowsOf(iso, hrs);
    $("bite-win").textContent = wins.map(([a, b]) => `${clock(a)}–${clock(b)}`).join(" and ") || "—";
    const start = data.days[iso][0];
    const curH = iso === isoToday ? Math.floor((now - start) / 3600) : -1;
    $("bite-bars").innerHTML = hrs.map((s, n) => {
      const w = wx[Math.floor((start + n * 3600 + 1800) / 3600)];
      return `<i class="b${band(s)}${n === curH ? " now" : ""}${n < curH ? " past" : ""}" style="height:${Math.max(6, s)}%" data-n="${n}" data-s="${s}"${w ? ` data-w="${Math.round(w.wind)}"` : ""}></i>`;
    }).join("");
    $("bite-factors").innerHTML = factorsHtml(iso, hrs);
    const sub = $("bite-sub");
    if (sub) sub.textContent = Object.keys(wx).length ? "Hour by hour, with live wind and weather" : sub.textContent;
    document.querySelectorAll("#bite-days button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.bd === iso));
      const h2 = adjusted(b.dataset.bd), raw = data.bite[b.dataset.bd];
      if (!raw) return;
      const t3 = [...h2].sort((a, c) => c - a).slice(0, 3), r3 = [...raw[1]].sort((a, c) => c - a).slice(0, 3);
      const s = Math.max(5, Math.min(98, Math.round(raw[0] + (t3.reduce((a, c) => a + c, 0) - r3.reduce((a, c) => a + c, 0)) / 3)));
      const tag = b.querySelector("b");
      tag.textContent = s; tag.className = `b${band(s)}`;
    });
    showHour(curH >= 0 ? curH : hrs.indexOf(Math.max(...hrs)), hrs);
  };

  const showHour = (n, hrs) => {
    const out = $("bite-hour");
    if (!out || n < 0 || n >= hrs.length) return;
    const start = data.days[iso][0], t = start + n * 3600 + 1800;
    const m = movement(t), w = wx[Math.floor(t / 3600)];
    const bits = [m ? (m.mv > 0.66 ? "strong tide flow" : m.mv > 0.33 ? "moderate flow" : "slack water") + (m.rising ? ", rising" : ", falling") : "",
      w ? `wind ${Math.round(w.wind)} mph` : "", w && w.pop >= 30 ? `${w.pop}% rain` : ""].filter(Boolean);
    const isNow = iso === isoToday && Math.floor((now - start) / 3600) === n;
    out.innerHTML = `<b>${isNow ? "Now" : hourLabel(n)}</b> · ${hrs[n]} ${LABEL[band(hrs[n])].toLowerCase()} · ${esc(bits.join(" · "))}`;
    document.querySelectorAll("#bite-bars i").forEach((b) => b.classList.toggle("sel", +b.dataset.n === n));
  };

  // The page may have been built yesterday: drop past days and say which one is today.
  document.querySelectorAll("#bite-days button").forEach((b) => {
    if (data.days[b.dataset.bd] && data.days[b.dataset.bd][1] <= now) b.remove();
    else if (b.dataset.bd === isoToday) b.querySelector("span").textContent = "Today";
  });
  $("bite-days").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-bd]");
    if (!b) return;
    iso = b.dataset.bd;
    render();
  });
  $("bite-bars").addEventListener("click", (e) => {
    const b = e.target.closest("i[data-n]");
    if (b) showHour(+b.dataset.n, adjusted(iso));
  });
  render();

  // ---- rain radar: NWS radar mosaic (sharp WMS images, last hour animated) on a USGS base map, both public domain ----
  const REGION = { AK: "alaska", HI: "hawaii", PR: "carib", VI: "carib", GU: "guam", MP: "guam", AS: null };
  const radar = () => {
    const box = $("bite-radar");
    const st = (data.name.match(/, ([A-Z]{2})$/) || [])[1];
    const region = st in REGION ? REGION[st] : "conus";
    if (!box || !region) return;
    box.hidden = false;
    let started = false;
    box.addEventListener("toggle", () => {
      if (!box.open || started) return;
      started = true;
      const holder = box.querySelector(".radar-box");
      holder.innerHTML = `<div class="radar-map" id="radar-map"></div><div class="radar-bar"><button type="button" id="radar-play" aria-label="Pause">❚❚</button><span id="radar-time">Loading radar…</span></div>` +
        `<p class="note">Rain and storms from National Weather Service radar, last hour. Green is light rain, yellow and red are heavy rain and storms. Base map: USGS The National Map.</p>`;
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css";
      document.head.appendChild(css);
      const js = document.createElement("script");
      js.src = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js";
      js.onload = () => draw(region).catch(() => { $("radar-time").textContent = "Radar isn't available right now."; });
      js.onerror = () => { $("radar-time").textContent = "Radar isn't available right now."; };
      document.head.appendChild(js);
    });
  };
  const draw = async (region) => {
    const L = window.L, lat = +live.dataset.lat, lng = +live.dataset.lng;
    const map = L.map("radar-map", { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView([lat, lng], 8);
    L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 16, attribution: "USGS The National Map" }).addTo(map);
    L.circleMarker([lat, lng], { radius: 6, color: "#fff", weight: 2, fillColor: "#d6336c", fillOpacity: 1 }).addTo(map);
    const url = `https://opengeo.ncep.noaa.gov/geoserver/${region}/${region}_bref_qcd/ows`;
    const caps = await fetch(`${url}?service=WMS&version=1.3.0&request=GetCapabilities`).then((r) => r.text());
    const dim = (caps.match(/<Dimension name="time"[^>]*>([^<]+)</) || [])[1] || "";
    const times = dim.split(",").map((x) => x.trim()).filter(Boolean);
    const recent = times.filter((t) => Date.parse(t) > Date.now() - 65 * 60e3);
    const step = Math.max(1, Math.round(recent.length / 8));
    const frames = recent.filter((_, i) => (recent.length - 1 - i) % step === 0).slice(-8);
    if (!frames.length) frames.push(times[times.length - 1]);
    // One full-size image per frame (no tile seams), redrawn for the visible area after each pan or zoom.
    const layers = frames.map(() => null);
    const frameUrl = (t) => {
      const b = map.getBounds(), size = map.getSize(), r = Math.min(2, window.devicePixelRatio || 1);
      const sw = L.CRS.EPSG3857.project(b.getSouthWest()), ne = L.CRS.EPSG3857.project(b.getNorthEast());
      return `${url}?service=WMS&version=1.3.0&request=GetMap&layers=${region}_bref_qcd&styles=&format=image/png&transparent=true` +
        `&crs=EPSG:3857&bbox=${sw.x},${sw.y},${ne.x},${ne.y}&width=${Math.round(size.x * r)}&height=${Math.round(size.y * r)}&time=${encodeURIComponent(t)}`;
    };
    const paint = () => frames.forEach((t, n) => {
      if (layers[n]) map.removeLayer(layers[n]);
      layers[n] = L.imageOverlay(frameUrl(t), map.getBounds(), { opacity: n === i ? 0.75 : 0, zIndex: 5,
        attribution: "NOAA / National Weather Service radar" }).addTo(map);
    });
    const fmt = (t) => new Date(t).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    let i = frames.length - 1, playing = true;
    paint();
    map.on("moveend", paint);
    const show = () => {
      layers.forEach((l, n) => l && l.setOpacity(n === i ? 0.75 : 0));
      $("radar-time").textContent = `${fmt(frames[i])}${i === layers.length - 1 ? " (latest)" : ""}`;
    };
    show();
    setInterval(() => { if (playing) { i = (i + 1) % layers.length; show(); } }, 700);
    $("radar-play").addEventListener("click", (e) => {
      playing = !playing;
      e.currentTarget.textContent = playing ? "❚❚" : "▶";
      e.currentTarget.setAttribute("aria-label", playing ? "Pause" : "Play");
      if (!playing) { i = layers.length - 1; show(); }
    });
  };

  // ---- live weather (NWS) ----
  const live = document.getElementById("live");
  const lat = live ? live.dataset.lat : null, lng = live ? live.dataset.lng : null;
  if (!lat) return;
  radar();
  const NWS = { headers: { Accept: "application/geo+json" } };
  const get = (u) => fetch(u, NWS).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  // "2026-10-11T03:00:00+00:00/PT3H" -> every epoch hour it covers
  const hoursOf = (vt) => {
    const [a, dur] = vt.split("/"), s = Date.parse(a) / 1000;
    const m = dur.match(/P(?:(\d+)D)?(?:T(?:(\d+)H)?)?/);
    const n = (+(m[1] || 0)) * 24 + (+(m[2] || 0)) || 1;
    return Array.from({ length: n }, (_, i) => Math.floor(s / 3600) + i);
  };
  const fill = (series, key, conv) => (series && series.values || []).forEach((v) => {
    if (v.value === null) return;
    for (const h of hoursOf(v.validTime)) (wx[h] = wx[h] || {})[key] = conv(v.value);
  });
  (async () => {
    let pt = null;
    for (const [dy, dx] of [[0, 0], [0.03, 0], [0, 0.03], [-0.03, 0], [0, -0.03]]) {
      pt = await get(`https://api.weather.gov/points/${(+lat + dy).toFixed(4)},${(+lng + dx).toFixed(4)}`).catch(() => null);
      if (pt && pt.properties && pt.properties.forecastGridData) break;
    }
    if (!pt || !pt.properties) return;
    const p = pt.properties;
    const kmh = (v) => v * 0.621371;
    try {
      const g = (await get(p.forecastGridData)).properties;
      fill(g.windSpeed, "wind", kmh);
      fill(g.windGust, "gust", kmh);
      fill(g.windDirection, "dir", (v) => COMPASS[Math.round(v / 22.5) % 16]);
      fill(g.probabilityOfPrecipitation, "pop", (v) => Math.round(v));
      for (const h of Object.keys(wx)) if (wx[h].wind === undefined) delete wx[h];
    } catch (e) { /* forecast unavailable: keep the tide-and-moon forecast */ }
    try {
      const sts = await get(p.observationStations);
      // The nearest station doesn't always report pressure: try the next few.
      for (const f of (sts.features || []).slice(0, 4)) {
        const obs = (await get(`https://api.weather.gov/stations/${f.properties.stationIdentifier}/observations?limit=12`).catch(() => ({}))).features || [];
        const pts = obs.map((o) => [Date.parse(o.properties.timestamp) / 1000, (o.properties.seaLevelPressure || {}).value || (o.properties.barometricPressure || {}).value])
          .filter(([t, v]) => v && now - t < 6 * 3600).sort((a, b) => b[0] - a[0]);
        const old = pts.find(([t]) => pts[0][0] - t >= 2.5 * 3600);
        if (pts.length && old) { pressure = { hpa: pts[0][1] / 100, trend: ((pts[0][1] - old[1]) / 100) * (3 * 3600 / (pts[0][0] - old[0])) }; break; }
      }
    } catch (e) { /* no pressure trend */ }
    render();
  })();
})();
