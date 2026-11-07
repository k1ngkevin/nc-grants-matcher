import os
import sys
import tempfile
from pathlib import Path

# Isolated database + outbox per test session; no scheduler threads.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="matchmaker-test-")
os.environ["RUN_SCHEDULER"] = "false"
os.environ["ENV_FILE"] = ""  # never pick up a developer's .env (it could hold real SMTP settings)
os.environ.setdefault("SEED_SAMPLE_IF_EMPTY", "true")
for k in ("SMTP_HOST", "ACS_CONNECTION_STRING","AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "SAM_API_KEY", "ALLOWED_EMAIL_DOMAINS"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
