# QUANTNEX Shared Finnhub News Service

This is a separate, read-only Cloudflare Worker. It lets every QUANTNEX installation use one Finnhub subscription without putting the Finnhub key in the browser, Windows app, repository, or users' local `.env` files. The existing local QUANTNEX API and local workspace data remain unchanged.

## Deploy once

1. Create/sign in to a Cloudflare account and install Node.js (LTS).
2. Open a terminal at `services/shared-news`.
3. Run `npx wrangler login` and complete the Cloudflare authorization.
4. Add the Finnhub key as a Cloudflare Worker secret (do not put it in a command argument, source file, or chat):
   `npx wrangler secret put FINNHUB_API_KEY`
   Paste the key only into the terminal prompt.
5. Deploy:
   `npx wrangler deploy`
6. Copy the Worker URL printed by Wrangler. Check its `/health` endpoint.

## Connect all QUANTNEX users

1. Open `apps/web/shared-news-config.js`.
2. Set `window.QUANTNEX_SHARED_NEWS_API_URL` to the Worker URL (without a trailing slash).
3. Commit and publish that small Web update. All users who receive the updated Web client will use the same shared Finnhub endpoint.

The API key remains a Cloudflare Worker secret. Only the public Worker URL is placed in the Web client. The endpoint supports read-only GET requests, validates the requested horizon (1–30 days), caps responses at 500 events, and uses Cloudflare edge caching to reduce repeated Finnhub requests. It never accepts arbitrary upstream URLs or returns the secret.

## Important limits and operations

- This service is not live until it is deployed and the public Worker URL is configured in `shared-news-config.js`.
- Finnhub plan quotas still apply. Edge caching is per Cloudflare cache location and uses the Worker response cache headers; it reduces but does not eliminate provider calls.
- The public endpoint serves economic calendar data only. Do not add wallet, journal, credentials, broker, or other personal data to this service.
- Rotate the Finnhub key in the Cloudflare dashboard if it is ever exposed. Update the Worker secret with `npx wrangler secret put FINNHUB_API_KEY` and redeploy.
- If the Worker URL changes, update the Web config and publish a new Web update.
- Local installations without the shared URL continue using the existing local Finnhub endpoint, so the current workflow remains available during rollout.
