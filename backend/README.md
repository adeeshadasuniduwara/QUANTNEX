# QUANTNEX Backend — Phase 04

FastAPI shared API foundation for Windows, Android and Web.

## Included
- Health endpoint and OpenAPI documentation.
- Registration/login, Argon2 password hashes and expiring JWT bearer tokens.
- Authenticated user profile.
- User-isolated trade journal list/create/delete APIs.
- User-isolated preferences read/write APIs.
- Optional server-side OpenAI-compatible AI chat gateway; disabled until configured.
- SQLite local development and PostgreSQL driver support.

## Run locally (Python 3.11+)

From the repository root:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set a unique QUANTNEX_SECRET_KEY in .env, then run:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health and http://127.0.0.1:8000/docs.

## API routes

| Method | Path | Auth |
|---|---|---|
| GET | /health | No |
| POST | /api/v1/auth/register | No |
| POST | /api/v1/auth/login | No |
| GET | /api/v1/auth/me | Bearer |
| GET, POST | /api/v1/journal | Bearer |
| DELETE | /api/v1/journal/{trade_id} | Bearer |
| GET | /api/v1/preferences | Bearer |
| PUT | /api/v1/preferences/{key} | Bearer |
| GET | /api/v1/ai/status | Bearer |
| POST | /api/v1/ai/chat | Bearer |

Set AI_BASE_URL, AI_API_KEY and AI_MODEL on the server only. The API key is never shipped to client applications.

## Production checklist

Use HTTPS, managed secrets, PostgreSQL, Alembic migrations, backups, rate limiting, audit logs, monitoring and security testing before public deployment. SQLite/create_all are development MVP choices. This API does not connect to brokers, fetch live prices, run bots or place orders.
