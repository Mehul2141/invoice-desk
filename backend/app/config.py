import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = BASE_DIR / "samples"
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
DB_PATH = STORAGE_DIR / "app.db"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
EXTRACTION_EFFORT = os.getenv("EXTRACTION_EFFORT", "medium")
NARRATIVE_EFFORT = os.getenv("NARRATIVE_EFFORT", "low")

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# Tried in order when the primary model is overloaded, rate limited or unavailable.
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-flash-latest,gemini-3.8-flash").split(",") if m.strip()]
GEMINI_TIMEOUT_S = int(os.getenv("GEMINI_TIMEOUT_S", "60"))

# Which model reads the invoices:
#   "auto"      — Claude if ANTHROPIC_API_KEY is set, else Gemini if GEMINI_API_KEY is set, else mock
#   "anthropic" — always Claude
#   "gemini"    — always Gemini
#   "mock"      — stored ground-truth extraction for the bundled samples (offline testing)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", os.getenv("EXTRACTION_MODE", "auto")).lower()

# Matching rules and approval policy live in the database (app/settings.py), editable in the UI.
TODAY = os.getenv("AP_TODAY", "2026-10-31")

# Minimum visible duration per stage so the live run view is readable.
STAGE_MIN_MS = int(os.getenv("STAGE_MIN_MS", "350"))


def provider() -> str:
    """The active extraction provider: 'anthropic', 'gemini' or 'mock'."""
    if LLM_PROVIDER == "anthropic":
        return "anthropic" if ANTHROPIC_API_KEY else "mock"
    if LLM_PROVIDER == "gemini":
        return "gemini" if GEMINI_API_KEY else "mock"
    if LLM_PROVIDER == "mock":
        return "mock"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if GEMINI_API_KEY:
        return "gemini"
    return "mock"


def provider_model() -> str:
    return {"anthropic": MODEL, "gemini": GEMINI_MODEL}.get(provider(), "mock (stored ground truth)")


def llm_enabled() -> bool:
    return provider() != "mock"
