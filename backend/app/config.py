import os
from dotenv import load_dotenv

# Load a local backend/.env when running from the backend directory.
load_dotenv()

ENVIRONMENT = os.getenv("QUANTNEX_ENV", "development").lower()
SECRET_KEY = os.getenv("QUANTNEX_SECRET_KEY", "local-development-only-change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./quantnex.db")
CORS_ORIGINS = ["http://127.0.0.1:5500", "http://localhost:5500"]
AI_BASE_URL = os.getenv("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

if ENVIRONMENT == "production" and SECRET_KEY == "local-development-only-change-me":
    raise ValueError("Set a strong QUANTNEX_SECRET_KEY in production.")
