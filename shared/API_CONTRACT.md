# Shared API Contract – Draft

This file defines initial conventions only. No production API exists in Phase 01.

## Conventions

- Base path: `/api/v1`
- Transport: HTTPS only outside local development.
- Encoding: UTF-8 JSON.
- Time: ISO 8601 UTC timestamps.
- IDs: opaque strings; never expose database credentials or internal secrets.

## Planned endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service health |
| GET | `/api/v1/app/version` | Current release metadata |
| GET | `/api/v1/market/overview` | Read-only market summary |
| GET | `/api/v1/bots` | List authorized bot status |
| GET | `/api/v1/notifications` | Retrieve user notifications |

These endpoints are design placeholders and are not implemented yet.

## Error shape

```json
{
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "The requested service is temporarily unavailable.",
    "request_id": "opaque-request-id"
  }
}
```

Never return API keys, broker tokens, passwords, stack traces or other secrets in API responses.
