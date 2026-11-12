# QUANTNEX Phase 04 — Shared Backend & Connectivity

## Implemented foundation

1. FastAPI service with health endpoint and OpenAPI docs.
2. Registration, login and authenticated user profile.
3. Argon2 password hashing and expiring JWT access tokens.
4. User-isolated trade journal list/create/delete APIs.
5. User-isolated preferences synchronization APIs.
6. Optional OpenAI-compatible AI gateway configured only on the server.
7. SQLite local development and PostgreSQL driver support.
8. Dockerfile, environment template, setup guide and schema tests.

## Local start

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set a unique QUANTNEX_SECRET_KEY in .env before using accounts.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open /docs for interactive API docs and /health for database status.

## Not yet completed

Windows, Android and Web clients are not yet connected to this API. Cloud deployment, domain/HTTPS, database migrations, rate limiting, backups, monitoring and security review are follow-up tasks. AI remains disabled until the server is configured. No live market feeds, broker connections, bot execution or order placement are included.
