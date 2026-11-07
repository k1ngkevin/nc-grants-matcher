"""Central configuration. Everything is read from environment variables so the
same container runs on a laptop (no keys) or in Azure (keys set)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "matchmaker.db"))
OUTBOX_DIR = DATA_DIR / "outbox"
WEB_DIST = Path(os.getenv("WEB_DIST", ROOT.parent / "web" / "dist"))

# Public URL of the site, used for links inside emails.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# ---- Guardrails (section 2 of the blueprint) ----
FINANCIAL_FLOOR = int(os.getenv("FINANCIAL_FLOOR", "50000"))  # hard minimum, users can only raise it
URGENT_DAYS = 14
STANDARD_MAX_DAYS = 60
# Grants.gov applicant-type codes NC state entities can apply under.
#   00 State governments, 06 Public & state-controlled institutions of higher education,
#   25 Others (see eligibility text), 99 Unrestricted
STATE_ELIGIBILITY_CODES = ["00", "06", "25", "99"]

# ---- Optional Azure OpenAI (embeddings + explanations) ----
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "")
AZURE_CHAT_DEPLOYMENT = os.getenv("AZURE_CHAT_DEPLOYMENT", "")
USE_AZURE_EMBEDDINGS = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and AZURE_EMBEDDING_DEPLOYMENT)
USE_AZURE_CHAT = bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY and AZURE_CHAT_DEPLOYMENT)

# ---- Optional SAM.gov (needs a free api.sam.gov key) ----
SAM_API_KEY = os.getenv("SAM_API_KEY", "")

# ---- Email ----
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "NC Federal Funds Matchmaker <no-reply@example.gov>")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
EMAIL_ENABLED = bool(SMTP_HOST)
# Comma-separated list, e.g. "nc.gov,unc.edu". Empty = allow any domain.
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]
# Double opt-in: a subscription only becomes active after the link in the confirmation email is clicked.
REQUIRE_EMAIL_CONFIRMATION = os.getenv("REQUIRE_EMAIL_CONFIRMATION", "true").lower() == "true"

# ---- Scheduling ----
RUN_SCHEDULER = os.getenv("RUN_SCHEDULER", "true").lower() == "true"
DAILY_INGEST_HOUR = int(os.getenv("DAILY_INGEST_HOUR", "6"))  # local server time
