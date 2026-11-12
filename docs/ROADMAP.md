# QUANTNEX Product Roadmap

QUANTNEX is developed as one evolving application. New capabilities should extend the existing shared workspace rather than create disconnected duplicate apps.

## Current foundation

- Monorepo for Web, Android, Windows and shared backend.
- Responsive Web workspace with position-size calculator and local trade journal.
- Windows desktop calculator and local SQLite journal.
- FastAPI foundation with authentication, user-isolated journal and preferences APIs.
- Optional server-side AI gateway.
- Automated backend tests and Windows build workflow.

## Next priorities

1. Bring Web and Windows UI into one consistent monochrome design system.
2. Connect Windows, Web and Android clients to the shared authenticated API.
3. Add secure Telegram notifications and bot status integration.
4. Add read-only market data adapters and watchlists.
5. Add bot control only after independent execution safeguards and risk limits are tested.
6. Publish signed Windows and Android releases with verified update and rollback flows.

## Safety boundaries

Current clients do not connect to brokers, stream live prices, run trading bots or place orders. Public deployment requires security review, operational monitoring, backups and testing. No profitability claims are made.
