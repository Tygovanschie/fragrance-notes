// fragrancenotes.app: the static site (../site) plus the open perfume database pages.
// Cloudflare serves the site files itself; only the paths in wrangler.jsonc "run_worker_first" reach fetch(),
// and they are fetched from the API server (server/pages.py) through api.fragrancenotes.app.
// Nothing about the visitor is passed on: no cookies, no IP headers, only the path and query.
//
// When the home server is down (restart, power or network), a page is served from the last good copy kept
// at Cloudflare (up to STALE_DAYS old), or else a short "back soon" page.
// scheduled() checks the server every few minutes and sends one email when it goes down and one when it
// is back (state in the KV namespace STATE; email through Cloudflare Email Routing, binding ALERT).

import { EmailMessage } from "cloudflare:email";

const API = "https://api.fragrancenotes.app";
// The database pages in English and under a language prefix (pages.LANGS), plus the photos, the stylesheet and
// the sitemap. /perfume/<id>/rate is the rating page the extension links to.
const LANG = "(?:nl|de|fr|es|it|pt|pl)";
const PAGES = new RegExp(
  `^(?:/${LANG})?/(?:database(?:/.*)?|perfume/[^/]+(?:/rate)?|note/[^/]+|notes|brand/[^/]+)$` +
  `|^/${LANG}/?$` +
  "|^/(?:photo/(?:n/)?[^/]+|assets/pages\\.css|sitemap\\.xml)$");   // photo/n/: note photos
const STALE_DAYS = 14;
const FROM = "alerts@fragrancenotes.app";

function staleKey(url) {
  return new Request(`https://stale.fragrancenotes.app${url.pathname}${url.search}`);
}

const DOWN_PAGE = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Back soon | Fragrance Notes</title>
<style>body{margin:0;background:#f4eef3;color:#2b1426;font:400 1.0625rem/1.6 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
main{max-width:34em}h1{font:800 2.4rem/1.05 system-ui,sans-serif;letter-spacing:-.03em;margin:0 0 14px}a{color:#7e2f63}</style></head>
<body><main><h1>Back in a moment</h1>
<p>The perfume database is being updated or restarted. Please try again in a few minutes.</p>
<p><a href="/">Fragrance Notes</a></p></main></body></html>`;

// A vote from the form on a perfume page (no JavaScript). Passed on with only what the server needs: the form,
// the page's origin, the voter cookie, and the visitor's address for the server's in-memory rate limit (never
// stored there). Never cached.
const VOTE = new RegExp(`^(?:/${LANG})?/perfume/[0-9a-f]{12}/vote$`);
async function sendVote(request, url) {
  const body = await request.text();
  if (body.length > 1000) return new Response("Too large", { status: 413 });
  const voter = (request.headers.get("Cookie") || "").split(";").map(c => c.trim()).find(c => /^fn_voter=[0-9a-f]{32}$/.test(c));
  const headers = { "Content-Type": "application/x-www-form-urlencoded", Origin: request.headers.get("Origin") || "" };
  if (voter) headers.Cookie = voter;
  const ip = request.headers.get("CF-Connecting-IP");
  if (ip) headers["X-Visitor-IP"] = ip;
  try {
    const r = await fetch(API + url.pathname, { method: "POST", headers, body, redirect: "manual", cf: { cacheTtl: 0 } });
    const out = new Headers(r.headers);
    out.delete("Access-Control-Allow-Origin");
    out.set("Cache-Control", "no-store");
    return new Response(r.body, { status: r.status, headers: out });
  } catch (err) {
    return new Response(DOWN_PAGE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
  }
}

async function fromServer(request, url, ctx) {
  const cache = caches.default;
  // Someone who voted (fn_voter cookie) sees their own vote filled in, and the page right after voting has a
  // personal message: both straight from the server with only that cookie, never cached or saved.
  const voter = (request.headers.get("Cookie") || "").split(";").map(c => c.trim()).find(c => /^fn_voter=[0-9a-f]{32}$/.test(c));
  const fresh = url.searchParams.has("vote") || !!voter;
  let upstream;
  try {
    upstream = await fetch(API + url.pathname + url.search, {
      method: request.method,
      headers: { Accept: request.headers.get("Accept") || "*/*", ...(voter ? { Cookie: voter } : {}) },
      redirect: "manual",
      // Cache at Cloudflare's edge as well, so the home server gets few requests.
      cf: fresh ? { cacheTtl: 0 } : { cacheTtlByStatus: { "200-299": 600, "301": 3600, "404": 300, "500-599": 0 } },
    });
  } catch (err) {
    upstream = null;
  }
  // 5xx, or Cloudflare's own errors when the tunnel is down (52x, 530): use the last good copy.
  if (!upstream || upstream.status >= 500) {
    const old = await cache.match(staleKey(url));
    if (old) {
      const h = new Headers(old.headers);
      h.set("Cache-Control", "no-store");
      h.set("X-Served-From", "saved copy");
      return new Response(old.body, { status: 200, headers: h });
    }
    return new Response(DOWN_PAGE, {
      status: 503,
      headers: { "Content-Type": "text/html; charset=utf-8", "Retry-After": "120", "Cache-Control": "no-store" },
    });
  }
  // Pass the answer on as it is (status, type, caching and security headers from the server).
  const headers = new Headers(upstream.headers);
  headers.delete("Access-Control-Allow-Origin");   // only the JSON API needs CORS
  if (fresh) headers.set("Cache-Control", "private, no-store");
  const response = new Response(upstream.body, { status: upstream.status, headers });
  if (upstream.status === 200 && request.method === "GET" && !fresh) {
    const copy = response.clone();
    const h = new Headers(copy.headers);
    h.set("Cache-Control", `public, max-age=${STALE_DAYS * 86400}`);
    ctx.waitUntil(cache.put(staleKey(url), new Response(copy.body, { status: 200, headers: h })));
  }
  return response;
}

async function healthy() {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await fetch(`${API}/health`, { cf: { cacheTtl: 0 }, signal: AbortSignal.timeout(10000) });
      if (r.ok) return true;
    } catch (err) { /* try once more */ }
    await new Promise((resolve) => setTimeout(resolve, 20000));
  }
  return false;
}

async function mail(env, subject, text) {
  if (!env.ALERT || !env.ALERT_TO) return;
  const raw = [
    `From: Fragrance Notes alerts <${FROM}>`,
    `To: ${env.ALERT_TO}`,
    `Subject: ${subject}`,
    `Message-ID: <${crypto.randomUUID()}@fragrancenotes.app>`,
    `Date: ${new Date().toUTCString()}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "",
    text,
  ].join("\r\n");
  await env.ALERT.send(new EmailMessage(FROM, env.ALERT_TO, raw));
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "POST" && VOTE.test(url.pathname)) {
      return sendVote(request, url);
    }
    if (!PAGES.test(url.pathname)) {
      return env.ASSETS.fetch(request);
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    return fromServer(request, url, ctx);
  },

  async scheduled(event, env, ctx) {
    if (!env.STATE) return;
    const ok = await healthy();
    const downSince = await env.STATE.get("downSince");
    const now = new Date().toISOString();
    if (!ok && !downSince) {
      await env.STATE.put("downSince", now);
      await mail(env, "Fragrance Notes API is down",
        `api.fragrancenotes.app/health did not answer (checked twice, 20 s apart) at ${now}.\n\n` +
        "The extension still works without it (Fragrantica data), but price comparison, confirmed notes and the " +
        "database pages are unavailable; the site shows saved copies of the pages.\n\n" +
        "Check the server (ubuntu-t): docker ps, docker logs fragrance-api, docker logs fragrance-cloudflared.");
    } else if (ok && downSince) {
      await env.STATE.delete("downSince");
      await mail(env, "Fragrance Notes API is back",
        `api.fragrancenotes.app answers again (${now}). It was down since ${downSince}.`);
    }
  },
};
