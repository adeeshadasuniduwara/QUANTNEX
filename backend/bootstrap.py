"""QUANTNEX first-run configuration and import/database preflight."""
from __future__ import annotations

from pathlib import Path
import secrets
import sys

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def prepare_environment() -> None:
    if not ENV_FILE.exists():
        if not EXAMPLE_FILE.exists():
            raise RuntimeError("backend/.env.example is missing; cannot create local configuration.")
        ENV_FILE.write_text(EXAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    values = dotenv_values(ENV_FILE)
    current = (values.get("QUANTNEX_SECRET_KEY") or "").strip()
    if not current or current == "local-development-only-change-me" or current.startswith("replace-with-"):
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        new_key = secrets.token_urlsafe(48)
        replaced = False
        output = []
        for line in lines:
            if line.strip().startswith("QUANTNEX_SECRET_KEY="):
                output.append("QUANTNEX_SECRET_KEY=" + new_key)
                replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append("QUANTNEX_SECRET_KEY=" + new_key)
        ENV_FILE.write_text("\n".join(output) + "\n", encoding="utf-8")
        print("Created a strong local QUANTNEX_SECRET_KEY in backend/.env (kept on this computer).", flush=True)

    load_dotenv(ENV_FILE, override=True)


def main() -> int:
    try:
        prepare_environment()
        import fastapi
        import sqlalchemy
        import uvicorn
        import cryptography
        from app.models import Base, User, Trade, Preference, WalletTransaction
        from app.main import app

        print(f"Python {sys.version.split()[0]} preflight: OK", flush=True)
        print(f"FastAPI {fastapi.__version__} · SQLAlchemy {sqlalchemy.__version__} · Uvicorn {uvicorn.__version__}", flush=True)
        print(f"ORM models loaded: {len(Base.metadata.tables)} tables", flush=True)
        print(f"QUANTNEX API import/database initialization: OK ({app.version})", flush=True)
        return 0
    except Exception as exc:
        print("\nQUANTNEX STARTUP DIAGNOSTIC FAILED", file=sys.stderr, flush=True)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        print("The API was not started. Check the message above; your local .env and database files were not deleted.", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
