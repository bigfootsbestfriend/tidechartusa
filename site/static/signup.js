// Email signups on station pages: buttons around the page ("Email me before minus tides", the alert banner,
// the trip planner) open the signup box with the right option ticked, and a small bar offers it once
// after someone has spent a while on the page. The bar is easy to dismiss and stays away for two weeks.
(() => {
  const card = document.getElementById("emails");
  if (!card) return;
  const form = card.querySelector("form");
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
  const subbed = () => store("tc-subbed");

  window.tcSignup = (want) => {
    if (want && want !== "all") {
      // Make sure the option they asked for is ticked; leave the others as they are.
      const box = form.querySelector(`input[name="${want}"]`);
      if (box) box.checked = true;
    }
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("flash");
    void card.offsetWidth;
    card.classList.add("flash");
    setTimeout(() => form.querySelector('input[type="email"]').focus({ preventScroll: true }), 500);
    hideBar();
  };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-signup]");
    if (b) { e.preventDefault(); window.tcSignup(b.dataset.signup); }
  });

  form.addEventListener("submit", () => {
    store("tc-subbed", "1");
    if (window.gtag) window.gtag("event", "sign_up", { method: "email", station: form.station.value });
  });

  // The one-time bar: after 25 seconds on the page or scrolling past the halfway point, never while the
  // signup box is on screen, and not again for 14 days once closed.
  const last = +store("tc-bar") || 0;
  if (subbed() || Date.now() - last < 14 * 864e5) return;
  const name = form.name.value;
  const bar = document.createElement("div");
  bar.className = "signup-bar";
  bar.hidden = true;
  bar.innerHTML = `<span><b>Free tide emails for ${name.replace(/</g, "&lt;")}</b> · the week's tides every Thursday</span>` +
    `<button type="button" class="go" data-signup="weekly">Sign up</button><button type="button" class="x" aria-label="No thanks">×</button>`;
  document.body.appendChild(bar);
  function hideBar() { bar.hidden = true; }
  bar.querySelector(".x").addEventListener("click", () => { store("tc-bar", String(Date.now())); bar.remove(); });
  let inView = false, shown = false;
  new IntersectionObserver(([en]) => { inView = en.isIntersecting; if (inView) hideBar(); }).observe(card);
  const show = () => {
    if (shown || inView || subbed()) return;
    shown = true;
    store("tc-bar", String(Date.now())); // counts as offered even if they ignore it
    bar.hidden = false;
  };
  setTimeout(show, 25000);
  addEventListener("scroll", () => {
    if (scrollY > (document.documentElement.scrollHeight - innerHeight) * 0.5) show();
  }, { passive: true });
})();
