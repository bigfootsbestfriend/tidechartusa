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
      const hits = data.s.filter(([name, st]) => { const n = norm(name + " " + st); return words.every((w) => n.includes(w)); })
        .sort((a, b) => norm(b[0]).startsWith(q) - norm(a[0]).startsWith(q)).slice(0, 10);
      box.innerHTML = hits.length
        ? hits.map(([name, st, path]) => `<a href="${data.base}${path}">${name.replace(/</g, "&lt;")} <span>${st}</span></a>`).join("")
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
})();
