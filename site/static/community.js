// Station page community bits, all anonymous: conditions reports, "Were today's times right?",
// the favorites count, and the Share button. Talks to the tide-alerts Worker (see alerts/src/index.js).
(() => {
  const card = document.getElementById("reports");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };

  // Share: the phone's share sheet where there is one, otherwise copy the link.
  document.querySelectorAll("[data-share]").forEach((b) => b.addEventListener("click", async () => {
    const name = document.querySelector("h1").textContent.replace(/ tide chart$/, "");
    const tides = [...document.querySelectorAll("#tlist li")].map((li) => li.textContent.replace(/\s+/g, " ").trim()).join(", ");
    const text = `Tides at ${name} today: ${tides}`;
    try {
      if (navigator.share) await navigator.share({ title: `${name} tides`, text, url: location.href.split("#")[0] });
      else { await navigator.clipboard.writeText(`${text}\n${location.href.split("#")[0]}`); b.querySelector("small").textContent = "Copied: paste it anywhere."; }
    } catch (e) { /* share sheet closed */ }
  }));

  if (!card) return;
  const api = card.dataset.api, station = card.dataset.station;
  const labels = JSON.parse(card.dataset.labels || "{}");
  const post = (path, body) => fetch(api + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json()).catch(() => ({ state: "error" }));
  const ago = (at) => {
    const m = Math.max(1, Math.round((Date.now() - Date.parse(at.replace(" ", "T") + "Z")) / 60000));
    return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`;
  };

  const paint = (d) => {
    const list = document.getElementById("rp-list");
    if (d.reports && d.reports.length) {
      list.innerHTML = d.reports.map((r) => `<li><span class="when">${ago(r.at)}</span>` +
        (r.chips ? r.chips.split(",").map((c) => `<span class="tag">${esc(labels[c] || c)}</span>`).join("") : "") +
        (r.note ? `<q>${esc(r.note)}</q>` : "") + "</li>").join("");
    }
    // Totals only show once they mean something.
    const votes = (d.up || 0) + (d.down || 0);
    if (votes >= 10) document.getElementById("acc-msg").textContent = `${Math.round(100 * d.up / votes)}% of ${votes} visitors said spot on.`;
    if ((d.favs || 0) >= 25) {
      const small = document.querySelector("[data-save] small");
      if (small && document.querySelector("[data-save]").getAttribute("aria-pressed") !== "true") small.textContent = `★ ${d.favs} people have this as a favorite.`;
    }
  };
  fetch(`${api}/community?station=${encodeURIComponent(station)}`).then((r) => r.json()).then(paint).catch(() => {});

  // Reports.
  card.addEventListener("click", (e) => {
    const c = e.target.closest("[data-chip]");
    if (c) c.setAttribute("aria-pressed", c.getAttribute("aria-pressed") !== "true");
  });
  const msg = document.getElementById("rp-msg");
  card.querySelector("[data-rp-send]").addEventListener("click", async (e) => {
    const chips = [...card.querySelectorAll('[data-chip][aria-pressed="true"]')].map((c) => c.dataset.chip);
    const note = document.getElementById("rp-note").value;
    if (!chips.length && note.trim().length < 3) { msg.textContent = "Tap at least one thing you saw."; return; }
    e.target.disabled = true;
    const r = await post("/report", { station, chips, note });
    e.target.disabled = false;
    msg.textContent = { ok: "Thanks! Your report is up.", nolinks: "Please leave out links, emails and phone numbers.",
      slow: "Thanks, you've sent a few already. Try again later.", empty: "Tap at least one thing you saw." }[r.state] || "Couldn't send that. Try again in a minute.";
    if (r.state === "ok") {
      card.querySelectorAll("[data-chip]").forEach((c) => c.setAttribute("aria-pressed", "false"));
      document.getElementById("rp-note").value = "";
      if (window.gtag) window.gtag("event", "conditions_report", { station });
      fetch(`${api}/community?station=${encodeURIComponent(station)}&t=${Date.now()}`).then((x) => x.json()).then(paint).catch(() => {});
    }
  });

  // Accuracy vote: once a day per station on this device.
  const acc = document.getElementById("acc");
  const today = new Date().toISOString().slice(0, 10);
  if (acc && store(`tc-acc-${station}`) !== today) {
    acc.hidden = false;
    acc.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-acc]");
      if (!b) return;
      store(`tc-acc-${station}`, today);
      acc.querySelectorAll("button").forEach((x) => (x.disabled = true));
      await post("/vote", { station, up: b.dataset.acc === "1" });
      document.getElementById("acc-msg").textContent = b.dataset.acc === "1" ? "Thanks!" : "Thanks. A report below helps others know what to expect.";
    });
  }

  // Favorites count: follow the Favorite button (app.js flips it first).
  document.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", () => setTimeout(() => {
    post("/fav", { station, on: b.getAttribute("aria-pressed") === "true" });
  }, 300)));
})();
