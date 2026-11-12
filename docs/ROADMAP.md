# QUANTNEX Development Roadmap

- Phase 01 — Monorepo foundation, platform skeletons, UI prototype and security boundaries.
- Phase 02 — Trading tools MVP: position sizing, local trade journal and bot monitor placeholder (web implementation).
- Phase 03 — Windows desktop MVP: plain Tkinter UI, position-size calculator, local SQLite journal, GitHub Releases update check and automated Windows EXE build artifact.
- Phase 04 — Shared backend foundation: FastAPI, Argon2/JWT authentication, user-isolated journal and preferences APIs, optional server-side AI gateway, SQLite development/PostgreSQL support, Dockerfile and tests. Client integration and cloud deployment remain follow-up tasks.
- Phase 05 — Connect platform clients to backend; add read-only market data adapters and watchlists.
- Phase 06 — Bot monitoring and controlled bot operations with independent execution service and risk guard.
- Phase 07 — Verified update service, signed manifests, staged rollout, health checks, backup and rollback.
- Phase 08 — AI assistant, market intelligence and advanced analytics.

Current clients and backend are development MVPs. They do not connect to brokers, stream live prices, run bots or place orders. Production deployment requires security review and operational testing. No profitability claims are made.
