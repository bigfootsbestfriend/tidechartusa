// Home page search (loads a small station index on first focus) and the state page filter.
(() => {
  const norm = (s) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const base = document.querySelector('link[rel="icon"]').getAttribute("href").replace(/static\/favicon\.svg$/, "");

  document.querySelectorAll("[data-search]").forEach((input) => {
    const box = input.parentElement.querySelector("[data-results]");
    let index = null;
    const load = () => index || (index = fetch(base + "static/search.json").then((r) => r.json()));
    input.addEventListener("focus", load);
    input.addEventListener("input", async () => {
      const q = norm(input.value);
      if (q.length < 2) { box.hidden = true; return; }
      const data = await load();
      const words = q.split(" ");
      const bare = (n) => norm(n.replace(/^Tides near /, ""));
      const hits = data.s.filter(([name, st, , , , alias]) => { const n = norm(`${name} ${st} ${alias || ""}`); return words.every((w) => n.includes(w)); })
        .sort((a, b) => bare(b[0]).startsWith(q) - bare(a[0]).startsWith(q) || (b[5] === "town") - (a[5] === "town")).slice(0, 10);
      box.innerHTML = hits.length
        ? hits.map(([name, st, path]) => `<a href="${data.base}${path}${input.dataset.suffix || ""}">${name.replace(/</g, "&lt;")} <span>${st}</span></a>`).join("")
        : `<div class="none">No station matches. Try the nearest town or bay, or <a href="${base}states/">browse by state</a>.</div>`;
      box.hidden = false;
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const a = box.querySelector("a"); if (a) location.href = a.href; }
    });
  });

  document.querySelectorAll("[data-filter]").forEach((input) => {
    const items = [...document.querySelectorAll("[data-n]")];
    input.addEventListener("input", () => {
      const q = norm(input.value);
      items.forEach((li) => { li.hidden = q && !norm(li.dataset.n).includes(q); });
    });
  });

  // "Find tides near me": nearest stations to the browser's location, from the same index.
  document.querySelectorAll("[data-locate]").forEach((btn) => {
    const msg = document.querySelector("[data-locate-msg]");
    const say = (html) => { msg.innerHTML = html; msg.hidden = false; };
    const rad = Math.PI / 180;
    const miles = (a, b, c, d) => 3958.8 * 2 * Math.asin(Math.sqrt(Math.sin((c - a) * rad / 2) ** 2 +
      Math.cos(a * rad) * Math.cos(c * rad) * Math.sin((d - b) * rad / 2) ** 2));
    btn.addEventListener("click", () => {
      if (!navigator.geolocation) { say("Your browser can't share a location. Try the search box instead."); return; }
      say("Finding your location…");
      navigator.geolocation.getCurrentPosition(async ({ coords }) => {
        const data = await fetch(base + "static/search.json").then((r) => r.json());
        const near = data.s.filter((s) => s[5] !== "town").map((s) => [miles(coords.latitude, coords.longitude, s[3], s[4]), s])
          .sort((a, b) => a[0] - b[0]).slice(0, 3);
        if (!near.length || near[0][0] > 150) { say("No tide stations within 150 miles of you. Try the search box."); return; }
        say("Nearest: " + near.map(([d, s]) => `<a href="${data.base}${s[2]}">${s[0].replace(/</g, "&lt;")}</a> (${Math.round(d)} mi)`).join(" · "));
      }, () => say("Location is blocked or unavailable. Try the search box instead."), { timeout: 10000, maximumAge: 600000 });
    });
  });
})();
