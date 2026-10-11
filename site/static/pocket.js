// Printable pocket card, tailored to an activity. Built from the page's own data (#tide-data) plus the
// radio box and wind forecast already on the page, with Tide Chart USA branding and a QR code back to the spot.
// Times and heights are written in feet/12-hour; units.js converts them if the visitor chose otherwise.
(() => {
  const el = document.getElementById("tide-data");
  const panel = document.getElementById("pocket-opts");
  const btn = document.querySelector("[data-pocket]");
  if (!el || !panel || !btn) return;
  const data = JSON.parse(el.textContent);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const txt = (n) => (n ? n.textContent.replace(/\s+/g, " ").trim() : "");
  let kind = "general", days = 7;

  btn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    btn.setAttribute("aria-expanded", !panel.hidden);
    if (!panel.hidden) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  panel.addEventListener("click", (e) => {
    const k = e.target.closest("[data-pk]"), d = e.target.closest("[data-days]");
    if (k) { kind = k.dataset.pk; panel.querySelectorAll("[data-pk]").forEach((b) => b.setAttribute("aria-pressed", b === k)); }
    if (d) { days = +d.dataset.days; panel.querySelectorAll("[data-days]").forEach((b) => b.setAttribute("aria-pressed", b === d)); }
    if (e.target.closest("[data-pk-print]")) make();
  });

  // Station-local clock from the start of that day (works in any visitor time zone).
  const clockIn = (d0) => (t) => {
    let m = Math.round((t - d0) / 60);
    m = ((m % 1440) + 1440) % 1440;
    const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, "0");
    return `${h % 12 || 12}:${mm} ${h < 12 ? "AM" : "PM"}`;
  };
  const ft = (v) => `${v.toFixed(1)} ft`;
  const RATE = ["Fair", "Fair", "Good", "Very good", "Excellent"];

  const loadQR = () => new Promise((ok) => {
    if (window.qrcode) return ok(true);
    const s = document.createElement("script");
    s.src = "https://cdnjs.cloudflare.com/ajax/libs/qrcode-generator/1.4.4/qrcode.min.js";
    s.onload = () => ok(true);
    s.onerror = () => ok(false);
    document.head.appendChild(s);
    setTimeout(() => ok(!!window.qrcode), 4000);
  });

  async function make() {
    const now = Date.now() / 1000;
    const list = Object.entries(data.days).filter(([, d]) => d[1] > now).slice(0, days);
    const name = data.name.replace(/, [A-Z]{2}$/, "");
    const url = location.href.split("#")[0];
    const wind = {};
    (window.tcWx || []).forEach((p) => { if (p.isDaytime) wind[p.startTime.slice(0, 10)] = `${p.windDirection} ${p.windSpeed}`; });
    const moonOf = (iso) => { const r = document.querySelector(`table.week tr[data-day="${iso}"]`); return r && r.cells[3] ? txt(r.cells[3]).replace(/ \(\d+%\)/, "") : ""; };

    const cols = {
      general: ["Day", "High and low tides", "Sunrise / sunset", "Moon"],
      fishing: ["Day", "Tides", "Rating", "Major periods", "Minor periods"],
      boating: ["Day", "Tides", data.cur ? "Slack water" : "Sunrise / sunset", data.cur ? "Strongest current" : "Wind (forecast)"],
      beach: ["Day", "Daylight low tides", "Best window", "Sunrise / sunset"],
    }[kind];
    if (kind === "boating" && data.cur) cols.push("Wind (forecast)");

    const rows = list.map(([iso, [s0, s1, rise, set, label]]) => {
      const c = clockIn(s0);
      const evs = data.ev.filter(([t]) => s0 <= t && t < s1);
      const tides = evs.map(([t, v, k]) => `<span class="${k}${v < 0 ? " minus" : ""}"><b>${k}</b> ${c(t)} ${ft(v)}</span>`).join("<br>");
      const sun = rise ? `${c(rise)} / ${c(set)}` : "—";
      const day = `<th>${esc(label.replace(/^(\w{3})\w*, (\w{3})\w* /, "$1 $2 "))}</th>`;
      if (kind === "fishing") {
        const f = (data.fish || {})[iso];
        const span = (m, h) => `${c(m - h)}–${c(m + h)}`;
        return `<tr>${day}<td>${tides}</td><td>${f ? RATE[f[0]] : "—"}</td><td>${f ? f[1].map((m) => span(m, 3600)).join("<br>") : "—"}</td>` +
          `<td>${f && f[2] ? f[2].map((m) => span(m, 1800)).join("<br>") : "—"}</td></tr>`;
      }
      if (kind === "boating") {
        const w = wind[iso] || "";
        if (!data.cur) return `<tr>${day}<td>${tides}</td><td>${sun}</td><td>${esc(w) || "—"}</td></tr>`;
        const cev = data.cur.ev.filter(([t]) => s0 <= t && t < s1);
        const slack = cev.filter((e) => e[2] === "S").map(([t]) => c(t)).join(", ") || "—";
        const peak = cev.filter((e) => e[2] !== "S").reduce((a, e) => (Math.abs(e[1]) > Math.abs(a ? a[1] : 0) ? e : a), null);
        const pk = peak ? `${Math.abs(peak[1]).toFixed(1)} kn ${peak[2] === "F" ? "flood" : "ebb"} at ${c(peak[0])}` : "—";
        return `<tr>${day}<td>${tides}</td><td>${slack}</td><td>${pk}</td><td>${esc(w) || "—"}</td></tr>`;
      }
      if (kind === "beach") {
        const lows = evs.filter(([t, , k]) => k === "L" && rise && t >= rise - 1800 && t <= set + 1800);
        const best = lows.reduce((a, e) => (!a || e[1] < a[1] ? e : a), null);
        return `<tr>${day}<td>${lows.map(([t, v]) => `<span class="L${v < 0 ? " minus" : ""}">${c(t)} ${ft(v)}</span>`).join("<br>") || "None in daylight"}</td>` +
          `<td>${best ? `${c(best[0] - 3600)}–${c(best[0] + 3600)}` : "—"}</td><td>${sun}</td></tr>`;
      }
      return `<tr>${day}<td>${tides}</td><td>${sun}</td><td>${esc(moonOf(iso))}</td></tr>`;
    }).join("");

    const tips = {
      general: "H = high, L = low. Bold heights are minus tides (below the chart's zero).",
      fishing: "Major periods (about 2 h) are when the moon is overhead or underfoot; minor (about 1 h) at moonrise and moonset. Moving water near a tide change often matters as much.",
      boating: data.cur ? `Currents from NOAA's ${esc(data.cur.name)} station. Slack is the calmest time to cross channels and inlets.` : "Smaller tides mean gentler currents. Check the marine forecast before you go.",
      beach: "Go about an hour before low tide and watch for the water coming back. Bold heights are minus tides, the best for tide pools.",
    }[kind];
    const opt = (k) => panel.querySelector(`[data-opt="${k}"]`).checked;
    let radio = "";
    if (opt("radio")) {
      const tx = [...document.querySelectorAll(".radio-tx li")].slice(0, 2).map((li) => esc(txt(li))).join("<br>");
      const same = txt(document.querySelector(".radio .note b"));
      radio = `<div class="pk-box"><b>VHF</b> 16 distress &amp; calling · 9 boater calling · 22A Coast Guard · 13 bridge-to-bridge` +
        (tx ? `<br><b>NOAA Weather Radio</b> ${tx}` : "") + (same ? `<br><b>Alert radio county code</b> ${esc(same)}` : "") +
        `<br><b>Emergency</b> VHF 16 or call 911</div>`;
    }
    const zone = txt(document.querySelector(".lv-fc h3")).replace(/^Marine forecast: /, "");
    const ok = await loadQR();
    let qr = "";
    if (ok && window.qrcode) {
      const q = window.qrcode(0, "M");
      q.addData(url);
      q.make();
      qr = q.createSvgTag({ cellSize: 2, margin: 0, scalable: true });
    }
    const title = { general: "Tides", fishing: "Fishing tides", boating: "Boating tides", beach: "Beach and tide pool tides" }[kind];

    document.getElementById("pocket")?.remove();
    const card = document.createElement("div");
    card.id = "pocket";
    card.innerHTML = `<header class="pk-head">
        <svg viewBox="0 0 32 32" class="pk-logo" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#0b5c7a"/><path d="M3 18c4 0 4-4 8-4s4 4 8 4 4-4 8-4 2 2 2 2v11H3z" fill="#7fd3e8"/><path d="M3 23c4 0 4-3 8-3s4 3 8 3 4-3 8-3 2 1 2 1v6H3z" fill="#fff"/></svg>
        <div><div class="pk-brand">Tide Chart USA</div><h1>${esc(title)}: ${esc(name)}</h1>
        <p class="pk-sub">${esc(txt(document.querySelector(".station .sub")).replace(/ · times in local time.*$/, ""))}${zone && kind === "boating" ? ` · Marine zone: ${esc(zone)}` : ""}</p></div>
      </header>
      <table><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>
      <p class="pk-tip">${tips}</p>
      ${radio}
      ${opt("notes") ? `<div class="pk-notes"><b>Notes</b>${"<span></span>".repeat(4)}</div>` : ""}
      <footer class="pk-foot">${qr ? `<div class="pk-qr">${qr}</div>` : ""}<div><b>tidechartusa.com</b><br>Scan for today's live chart, weather and warnings.
      Free tide emails and an offline app at tidechartusa.com.<br><small>Printed ${new Date().toLocaleDateString()} · NOAA predictions in local time · not for navigation</small></div></footer>`;
    document.body.appendChild(card);
    document.body.classList.add("print-pocket");
    if (window.gtag) window.gtag("event", "pocket_card", { kind, days });
    const done = () => { document.body.classList.remove("print-pocket"); card.remove(); removeEventListener("afterprint", done); };
    addEventListener("afterprint", done);
    setTimeout(() => window.print(), 100); // let units.js convert the new text first
  }
})();
