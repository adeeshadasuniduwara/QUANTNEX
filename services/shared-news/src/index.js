/**
 * QUANTNEX Shared Finnhub Economic Calendar
 *
 * Deploy as a Cloudflare Worker. FINNHUB_API_KEY is a Worker secret and is
 * never returned to callers. This endpoint exposes read-only economic events.
 */
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=60, s-maxage=300",
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-allow-headers": "Accept, Content-Type",
  "vary": "Origin",
};

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...JSON_HEADERS, ...extra },
  });
}

function validDays(value) {
  const parsed = Number.parseInt(value || "7", 10);
  if (!Number.isFinite(parsed)) return 7;
  return Math.min(30, Math.max(1, parsed));
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: JSON_HEADERS });
    }
    if (request.method !== "GET") {
      return json({ detail: "Only GET requests are supported." }, 405);
    }
    if (url.pathname === "/health") {
      return json({ status: "ok", service: "quantnex-shared-news", provider: "Finnhub" });
    }
    if (url.pathname !== "/api/economic-calendar") {
      return json({ detail: "Not found." }, 404);
    }
    if (!env.FINNHUB_API_KEY) {
      return json({ configured: false, provider: "Finnhub", events: [],
        note: "Shared Finnhub service is missing its server-side API secret." }, 503);
    }

    const days = validDays(url.searchParams.get("days"));
    const cacheUrl = new URL("/cached-economic-calendar", url.origin);
    cacheUrl.searchParams.set("days", String(days));
    const cacheKey = new Request(cacheUrl.toString(), { method: "GET" });
    const cache = caches.default;
    const cached = await cache.match(cacheKey);
    if (cached) return cached;

    const now = new Date();
    const from = now.toISOString().slice(0, 10);
    const toDate = new Date(now.getTime() + days * 86400000);
    const to = toDate.toISOString().slice(0, 10);
    const upstream = new URL("https://finnhub.io/api/v1/calendar/economic");
    upstream.searchParams.set("from", from);
    upstream.searchParams.set("to", to);
    upstream.searchParams.set("token", env.FINNHUB_API_KEY);

    try {
      const response = await fetch(upstream.toString(), {
        headers: { "accept": "application/json" },
        signal: AbortSignal.timeout(12000),
      });
      if (!response.ok) {
        const status = response.status === 429 ? 503 : 502;
        return json({ detail: response.status === 429
          ? "Finnhub provider quota is temporarily exhausted. Please retry later."
          : "Finnhub is temporarily unavailable. Please retry later." }, status,
          { "cache-control": "no-store" });
      }
      const payload = await response.json();
      if (!payload || typeof payload !== "object" || !Array.isArray(payload.economicCalendar)) {
        return json({ detail: "Finnhub returned an invalid economic calendar response." }, 502,
          { "cache-control": "no-store" });
      }
      const events = payload.economicCalendar.slice(0, 500);
      events.sort((a, b) => String(a.time || a.date || "").localeCompare(String(b.time || b.date || "")));
      const result = json({
        configured: true,
        provider: "Finnhub",
        from,
        to,
        events,
        timestamp: new Date().toISOString(),
        timezone: "UTC provider timestamps; QUANTNEX displays Asia/Colombo local time",
        note: "Shared live Finnhub economic calendar. Confirm release details before trading.",
      });
      ctx.waitUntil(cache.put(cacheKey, result.clone()));
      return result;
    } catch {
      return json({ detail: "Shared Finnhub service could not reach the provider. Please retry later." }, 502,
        { "cache-control": "no-store" });
    }
  },
};
