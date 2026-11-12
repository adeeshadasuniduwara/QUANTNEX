import os
from dotenv import load_dotenv

# Load a local backend/.env when running from the backend directory.
load_dotenv()

ENVIRONMENT = os.getenv("QUANTNEX_ENV", "development").lower()
SECRET_KEY = os.getenv("QUANTNEX_SECRET_KEY", "local-development-only-change-me")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./quantnex.db")
TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8501,http://localhost:5500,http://127.0.0.1:5500").split(",") if x.strip()]
AI_BASE_URL = os.getenv("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")

if not 5 <= TOKEN_MINUTES <= 1440:
    raise ValueError("ACCESS_TOKEN_MINUTES must be between 5 and 1440.")
if ENVIRONMENT == "production" and SECRET_KEY == "local-development-only-change-me":
    raise ValueError("Set a strong QUANTNEX_SECRET_KEY in production.")
