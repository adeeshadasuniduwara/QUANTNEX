/**
 * QUANTNEX Shared Finnhub Economic Calendar.
 * The Finnhub key is a Cloudflare Worker secret and is never returned.
 */
const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=60",
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
  return Number.isFinite(parsed) ? Math.min(30, Math.max(1, parsed)) : 7;
}

function eventDay(event) {
  const raw = event?.time ?? event?.date;
  if (typeof raw === "number" || /^\d{10,13}$/.test(String(raw || ""))) {
    const numeric = Number(raw);
    return new Date(numeric * (String(raw).length === 13 ? 0.001 : 1)).toISOString().slice(0, 10);
  }
  return String(raw || "").slice(0, 10);
}

function responseFor(payload, days) {
  const from = new Date().toISOString().slice(0, 10);
  const end = new Date(Date.now() + days * 86400000);
  const to = end.toISOString().slice(0, 10);
  const events = (Array.isArray(payload.events) ? payload.events : [])
    .filter(event => {
      const day = eventDay(event);
      return day >= from && day <= to;
    })
    .slice(0, 500);
  return json({
    configured: true,
    provider: "Finnhub",
    from,
    to,
    events,
    timestamp: payload.timestamp,
    timezone: "UTC provider timestamps; QUANTNEX displays Asia/Colombo local time",
    note: "Shared live Finnhub economic calendar. Confirm release details before trading.",
  });
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
        note: "Shared Finnhub service is missing its server-side API secret." }, 503,
        { "cache-control": "no-store" });
    }

    const days = validDays(url.searchParams.get("days"));
    const from = new Date().toISOString().slice(0, 10);
    const cacheUrl = new URL("/cached-economic-calendar", url.origin);
    cacheUrl.searchParams.set("date", from);
    const cacheKey = new Request(cacheUrl.toString(), { method: "GET" });
    const cache = caches.default;
    let payload;
    const cached = await cache.match(cacheKey);
    if (cached) {
      payload = await cached.json();
    } else {
      const to = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
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
          return json({ detail: response.status === 429
            ? "Finnhub provider quota is temporarily exhausted. Please retry later."
            : "Finnhub is temporarily unavailable. Please retry later." }, 502,
            { "cache-control": "no-store" });
        }
        const data = await response.json();
        if (!data || typeof data !== "object" || !Array.isArray(data.economicCalendar)) {
          return json({ detail: "Finnhub returned an invalid economic calendar response." }, 502,
            { "cache-control": "no-store" });
        }
        const events = data.economicCalendar.slice(0, 1000)
          .sort((a, b) => eventDay(a).localeCompare(eventDay(b)));
        payload = { events, timestamp: new Date().toISOString() };
        const cacheResponse = json(payload, 200, { "cache-control": "public, max-age=300" });
        ctx.waitUntil(cache.put(cacheKey, cacheResponse));
      } catch {
        return json({ detail: "Shared Finnhub service could not reach the provider. Please retry later." }, 502,
          { "cache-control": "no-store" });
      }
    }
    return responseFor(payload, days);
  },
};
