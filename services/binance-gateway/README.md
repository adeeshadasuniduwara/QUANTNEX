# QUANTNEX Binance Mobile Gateway

A separate HTTPS service that lets a user connect Binance Spot Testnet and USD-M Futures Testnet from a phone opened through their existing QUANTNEX Telegram bot. It does **not** expose the local QUANTNEX API and does not submit orders.

## Security model

- The local QUANTNEX worker generates a random 256-bit workspace capability and stores it in its local encrypted-preference database. It is sent only to this service over HTTPS in the `X-QUANTNEX-Workspace-Key` header.
- The gateway stores only a SHA-256 hash of that workspace capability.
- A setup session is random, expires after five minutes, is invalidated when a new link is issued, and is consumed before Binance verification to prevent replay/concurrent submissions.
- The one-time token is placed in the URL fragment (`#...`). Browsers do not send URL fragments in HTTP requests or Referer headers; the page removes it from the address bar immediately.
- Credentials are submitted directly to the gateway over HTTPS, verified against Binance TESTNET, and encrypted at rest with a dedicated Fernet key. No credential endpoint returns stored values.
- Do not forward the one-time link. Anyone holding it before expiry can attempt the one-time setup. Use it only from the private Telegram chat where it was delivered.
- The service has no live Binance endpoints and no order-placement route. Auto Trading remains OFF.

The workspace capability is a bearer secret. Protect the local QUANTNEX database and do not share its contents. Rotate it by deleting the local `binance_gateway_workspace_key` preference and provisioning a new gateway workspace after disconnecting the old record.

## Deploy

Deploy `services/binance-gateway/Dockerfile` to a managed container host with a persistent PostgreSQL database and HTTPS ingress. Do not use ephemeral container storage for production data.

Required environment variables:
- `DATABASE_URL`: PostgreSQL connection URL.
- `QUANTNEX_GATEWAY_PUBLIC_URL`: public HTTPS origin, e.g. `https://binance-gateway.example.com`.
- `QUANTNEX_GATEWAY_ENCRYPTION_KEY`: a dedicated Fernet key generated with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Store it in the hosting provider's secret manager. Back it up securely; losing it makes saved credentials unrecoverable.

The service deliberately refuses to start without an encryption key and HTTPS public URL. Do not commit secrets or put them in the Web bundle. Use TLS at the ingress, persistent database backups, restricted operator access, and a deployment platform that supports secret management.

## Connect local QUANTNEX workers

After deploying the gateway, add these variables to each local QUANTNEX Backend environment (not to browser JavaScript):
- `QUANTNEX_BINANCE_GATEWAY_URL=https://binance-gateway.example.com`

Restart the local Backend. The worker creates a private workspace capability automatically on first use. Then send `/binance` to the connected QUANTNEX Telegram bot and tap **Open Secure Binance Setup**.

If the gateway URL is not configured, `/binance` keeps showing the existing dashboard instructions. The local-only Binance Exchange page continues to work as before.

## Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Non-sensitive health status |
| GET | `/setup` | Mobile setup page |
| POST | `/v1/setup-sessions` | Create a one-time link; requires workspace capability |
| POST | `/v1/setup-sessions/complete` | Consume link, verify TESTNET keys, encrypt and save |
| GET | `/v1/workspaces/status` | Connection status; requires workspace capability |
| DELETE | `/v1/workspaces/credentials` | Delete encrypted TESTNET credentials; requires workspace capability |

The gateway stores no Telegram bot token, Telegram chat message, Binance live key, or order history. Telegram chat ID is retained only as setup-session metadata and is not used as authentication.
