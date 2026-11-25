// fragrancenotes.app: the static site (../site) plus the open perfume database pages.
// Cloudflare serves the site files itself; only the paths in wrangler.jsonc "run_worker_first" reach this
// code, and they are fetched from the API server (server/pages.py) through api.fragrancenotes.app.
// Nothing about the visitor is passed on: no cookies, no IP headers, only the path and query.

const API = "https://api.fragrancenotes.app";
const PAGES = /^\/(database(\/.*)?|perfume\/[^/]+|note\/[^/]+|photo\/[^/]+|assets\/pages\.css|sitemap\.xml)$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!PAGES.test(url.pathname)) {
      return env.ASSETS.fetch(request);
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    const upstream = await fetch(API + url.pathname + url.search, {
      method: request.method,
      headers: { Accept: request.headers.get("Accept") || "*/*" },
      redirect: "manual",
      // Cache at Cloudflare's edge as well, so the home server gets few requests.
      cf: { cacheTtlByStatus: { "200-299": 600, "301": 3600, "404": 300, "500-599": 0 } },
    });
    // Pass the answer on as it is (status, type, caching and security headers from the server).
    const headers = new Headers(upstream.headers);
    headers.delete("Access-Control-Allow-Origin");   // only the JSON API needs CORS
    return new Response(upstream.body, { status: upstream.status, headers });
  },
};
