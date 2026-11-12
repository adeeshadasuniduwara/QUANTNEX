# QUANTNEX Device-Hosted Data Architecture

## Recommended model

QUANTNEX must not expose the laptop's SQLite/PostgreSQL port or a development server directly to the public Internet. Public clients communicate only with an authenticated HTTPS API. The API validates each user's identity and scopes every record to that user.

## Laptop identity

- On first host setup, QUANTNEX generates a random installation UUID and a cryptographic host key pair.
- The private host key is protected by Windows DPAPI and is never uploaded as a hardware fingerprint.
- The public key and installation UUID identify the registered QUANTNEX host. A user can revoke that host from account security settings.
- Do not identify the laptop using MAC address, serial number, disk ID, or other invasive hardware fingerprinting.

## Offline behaviour

A laptop that is powered off cannot receive Internet requests. Therefore, users cannot directly register against that laptop while it is offline.

For sign-ups and data submissions during host downtime, a small HTTPS relay/queue must remain online. Clients submit encrypted, authenticated events to the relay; the relay stores only the minimum queued payload. When the laptop reconnects, it authenticates to the relay, downloads pending events, verifies signatures and idempotency keys, and imports each event into the host database. The relay removes an event only after the host acknowledges durable storage.

If QUANTNEX does not use an always-on relay or cloud API, the honest alternative is to mark offline registrations as pending on each client and synchronize them only after the laptop is online. Those registrations cannot be globally confirmed or used on another device until synchronization succeeds.

## Privacy and isolation requirements

- Every database row containing user data must include a user/tenant owner ID and every read/write query must enforce it server-side.
- Use TLS for all Internet traffic, strong password hashing, short-lived access tokens, rate limits, audit logs, encrypted backups, and tested restore procedures.
- Use per-user authorization and separate host administration permissions. The laptop owner must not automatically gain access to private user journals.
- Encrypt queued relay payloads for the registered host; keep encryption keys off the relay.
- Never expose database credentials, API secrets, or host private keys in Web, APK, or EXE bundles.
- Provide user export, account deletion, host revocation, and synchronization conflict handling.

## Operational limitation

A personal laptop is not a reliable public production server: sleep, shutdown, power loss, ISP outages, changing IP addresses, and carrier-grade NAT can interrupt service. Keep the cloud relay/API available for authentication and queuing, and treat the laptop as a private primary archive or replica only after a tested synchronization and backup design is implemented.

## Current implementation status

The existing backend has account registration/login and user-scoped journal endpoints, but the Web, Windows, and Android clients are not yet integrated with one shared production API. This document is the required security design; it does not claim that host registration, encrypted relay queues, offline synchronization, or public hosting are already implemented.