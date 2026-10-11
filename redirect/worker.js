// tidechartusa.com was renamed to Shorebite: send every old address to the same page on shorebite.com.
// Search engines, scripts and anything that isn't a browser page view get a plain 301. A person's browser gets a tiny
// page instead that copies their favorites and settings (kept per website in localStorage, so shorebite.com can't see
// them) into the new address; shorebite.com's page() reads ?sbmove= and saves them there.
const BOT = /bot|crawl|spider|slurp|archiver|facebookexternalhit|embedly|preview|monitor|lighthouse|curl|wget|python|httpclient|okhttp|java\//i;
const KEYS = ["tc-saved", "tc-units", "tc-subbed", "tc-bar"];

export default {
  fetch(req) {
    const u = new URL(req.url);
    const dest = `https://shorebite.com${u.pathname}${u.search}`;
    const ua = req.headers.get("user-agent") || "";
    const page = req.method === "GET" && (req.headers.get("accept") || "").includes("text/html") && ua && !BOT.test(ua);
    if (!page) return Response.redirect(dest, 301);
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Shorebite</title>
<meta name="robots" content="noindex"><link rel="canonical" href="${dest.replace(/"/g, "&quot;")}">
<noscript><meta http-equiv="refresh" content="0;url=${dest.replace(/"/g, "&quot;")}"></noscript>
<script>(function(){var d=${JSON.stringify(dest)},o={},n=0;
try{${JSON.stringify(KEYS)}.forEach(function(k){var v=localStorage.getItem(k);if(v){o[k]=v;n++}})}catch(e){}
if(n)d+=(d.indexOf("?")<0?"?":"&")+"sbmove="+encodeURIComponent(JSON.stringify(o));
location.replace(d+location.hash)})()</script></head>
<body style="font:16px system-ui;padding:2rem;color:#11232c">Tide Chart USA is now <a href="${dest.replace(/"/g, "&quot;")}">Shorebite</a>. Taking you there…</body></html>`;
    return new Response(html, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" } });
  },
};
