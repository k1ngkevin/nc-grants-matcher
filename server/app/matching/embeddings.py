"""Vector similarity between opportunities and agency text (mission, strategic plans, projects).

Two interchangeable backends:
  * Azure OpenAI embeddings  - used when AZURE_OPENAI_* + AZURE_EMBEDDING_DEPLOYMENT are set AND every
                               opportunity has a stored vector (computed at ingest, or with
                               `python -m app.ingest --embed`).
  * Local TF-IDF             - no keys, no network; good enough for demos and tests.

Azure is never allowed to take the site down: if its vectors are missing, or a call fails
(wrong deployment name, bad key, timeout), matching falls back to local TF-IDF and logs why.
After a failed call Azure is left alone for AZURE_COOLDOWN_SECONDS before it's tried again.

Both expose the same thing: cosine similarity in [0, 1] plus a calibrate() that maps raw
similarity onto a 0-1 "fit" scale (the two backends produce very different raw ranges).

Production note: the blueprint stores vectors in Azure AI Search. With ~2,000 open
opportunities an in-memory matrix is fast enough; swap `Index` for an Azure AI Search
vector query when the corpus grows (same inputs/outputs).
"""
import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np
import requests

from .. import config, db

log = logging.getLogger(__name__)
_lock = threading.Lock()
_indexes: dict = {}  # wanted backend -> Index
_query_cache: dict[str, np.ndarray] = {}
_azure_down_until = 0.0  # time.monotonic() until which Azure embeddings are skipped

# Raw cosine -> 0..1 fit. Tuned on the sample set; re-tune with `python -m app.evaluate`.
CALIBRATION = {"tfidf": (0.02, 0.22), "azure": (0.20, 0.55)}
AZURE_COOLDOWN_SECONDS = 300
QUERY_TIMEOUT = 15     # a web request is waiting on this
BATCH_TIMEOUT = 60     # ingest / --embed
BATCH_SIZE = 16        # opportunities per embeddings request; small enough for default quotas
BATCH_RETRIES = 5      # for 429 / 5xx / network errors during ingest


class EmbeddingError(Exception):
    """Azure OpenAI embeddings can't be used right now. The message says why, in plain words."""


def backend() -> str:
    """The configured backend (what the settings ask for)."""
    return "azure" if config.USE_AZURE_EMBEDDINGS else "tfidf"


def _wanted() -> str:
    return "azure" if config.USE_AZURE_EMBEDDINGS and time.monotonic() >= _azure_down_until else "tfidf"


def active_backend() -> str:
    """The backend matching actually uses right now (for /api/meta)."""
    if _wanted() != "azure":
        return "tfidf"
    idx = _indexes.get("azure")
    if idx is not None and idx.version == _version():
        return idx.kind
    s = vector_status()
    return "azure" if s["total"] and s["with_vector"] == s["total"] else "tfidf"


def vector_status() -> dict:
    with db.session() as conn:
        total, with_vector = conn.execute("SELECT COUNT(*), COUNT(embedding) FROM opportunities").fetchone()
    return {"total": total, "with_vector": with_vector}


def calibrate(sim: float, kind: str | None = None) -> float:
    lo, hi = CALIBRATION[kind or backend()]
    return float(min(1.0, max(0.0, (sim - lo) / (hi - lo))))


def opportunity_text(o: dict) -> str:
    parts = [o.get("title", ""), o.get("title", ""), o.get("federal_agency") or "",
             " ".join(o.get("categories") or []), (o.get("description") or "")[:4000]]
    return " ".join(p for p in parts if p)


def chunk(text: str, size: int = 1500) -> list[str]:
    """Split long documents (strategic plans) so one vector doesn't average away the detail."""
    words, out, cur = text.split(), [], []
    for w in words:
        cur.append(w)
        if sum(len(x) + 1 for x in cur) >= size:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out or [""]


# ---------------- Azure OpenAI ----------------
def _explain_http_error(r: requests.Response) -> str:
    try:
        err = r.json()["error"]
        code, message = err.get("code"), err.get("message", "")
    except (ValueError, KeyError, TypeError, AttributeError):
        code, message = None, r.text[:300]
    where = config.AZURE_OPENAI_ENDPOINT
    if r.status_code == 404 and code == "DeploymentNotFound":
        return (f"Azure OpenAI at {where} has no deployment named '{config.AZURE_EMBEDDING_DEPLOYMENT}'. "
                "Deploy an embedding model under that name in Azure AI Foundry (or set AZURE_EMBEDDING_DEPLOYMENT "
                "to an existing deployment's name), or remove the AZURE_OPENAI_* settings to use local matching.")
    if r.status_code in (401, 403):
        return f"Azure OpenAI at {where} refused the key ({r.status_code}). Check AZURE_OPENAI_KEY. {message}".strip()
    return f"Azure OpenAI embeddings returned {r.status_code}: {message}".strip()


def _retry_wait(r: requests.Response | None, attempt: int) -> float:
    if r is not None:
        for header, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
            try:
                return min(60.0, float(r.headers[header]) * scale + 0.5)
            except (KeyError, ValueError, TypeError):
                pass
    return min(60.0, 2.0 * 2 ** attempt)


def _embed_batch(texts: list[str], timeout: float, retries: int) -> list[list[float]]:
    url = (f"{config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{config.AZURE_EMBEDDING_DEPLOYMENT}"
           f"/embeddings?api-version={config.AZURE_OPENAI_API_VERSION}")
    payload = {"input": [t[:8000] or " " for t in texts]}
    for attempt in range(retries + 1):
        r = None
        try:
            r = requests.post(url, headers={"api-key": config.AZURE_OPENAI_KEY}, json=payload, timeout=timeout)
        except requests.RequestException as e:
            if attempt == retries:
                raise EmbeddingError(f"Couldn't reach Azure OpenAI at {config.AZURE_OPENAI_ENDPOINT}: {e}") from e
        else:
            if r.ok:
                try:
                    return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
                except (ValueError, KeyError, TypeError) as e:
                    raise EmbeddingError(f"Azure OpenAI embeddings sent a response we couldn't read: {e}") from e
            if not (r.status_code == 429 or r.status_code >= 500) or attempt == retries:
                raise EmbeddingError(_explain_http_error(r))
        wait = _retry_wait(r, attempt)
        log.info("Azure OpenAI embeddings busy or unreachable; retrying in %.0fs", wait)
        time.sleep(wait)
    raise AssertionError("unreachable")


def _normalize(m: np.ndarray) -> np.ndarray:
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)


def azure_embed(texts: list[str], timeout: float = QUERY_TIMEOUT, retries: int = 0) -> np.ndarray:
    """Embed texts with Azure OpenAI. Raises EmbeddingError with a readable reason on failure."""
    vecs = []
    for i in range(0, len(texts), BATCH_SIZE):
        vecs.extend(_embed_batch(texts[i:i + BATCH_SIZE], timeout, retries))
    return _normalize(np.array(vecs, dtype=np.float32))


def refresh_opportunity_embeddings(redo_all: bool = False, progress=None) -> int:
    """Embed opportunities that don't have a vector yet (all of them with redo_all=True).
    Called after ingest and by `python -m app.ingest --embed`. Saves after every batch, so a
    failure part-way keeps the work already done. Returns how many were embedded; raises
    EmbeddingError if Azure can't be used."""
    if backend() != "azure":
        return 0
    with db.session() as conn:
        where = "" if redo_all else " WHERE embedding IS NULL"
        rows = [db.row_to_dict(r) for r in conn.execute(f"SELECT id, title, federal_agency, categories, description FROM opportunities{where}")]
    done = 0
    try:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            vecs = _normalize(np.array(_embed_batch([opportunity_text(r) for r in batch], BATCH_TIMEOUT, BATCH_RETRIES),
                                       dtype=np.float32))
            with db.session() as conn:
                for r, v in zip(batch, vecs):
                    conn.execute("UPDATE opportunities SET embedding=? WHERE id=?", (json.dumps(v.round(5).tolist()), r["id"]))
            done += len(batch)
            if progress:
                progress(done, len(rows))
    finally:
        if done:
            # Tells running servers (even in another process) to rebuild their index.
            db.set_meta("embeddings_version", datetime.now(timezone.utc).isoformat(timespec="microseconds"))
            log.info("Embedded %s opportunities with Azure OpenAI", done)
    return done


def _trip(err: Exception) -> None:
    global _azure_down_until
    _azure_down_until = time.monotonic() + AZURE_COOLDOWN_SECONDS
    log.error("Azure OpenAI embeddings failed, so matching uses local text similarity for the next %d minutes. %s",
              AZURE_COOLDOWN_SECONDS // 60, err)


# ---------------- Index ----------------
def _version() -> tuple:
    return db.get_meta("ingest_version"), db.get_meta("embeddings_version")


class Index:
    def __init__(self, want: str = "tfidf", version: tuple | None = None):
        with db.session() as conn:
            rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM opportunities")]
        self.ids = [r["id"] for r in rows]
        self.pos = {oid: i for i, oid in enumerate(self.ids)}
        self.version = version if version is not None else _version()
        self.kind = "tfidf"
        if want == "azure" and rows:
            vecs = [r.get("embedding") for r in rows]
            missing = sum(not isinstance(v, list) for v in vecs)
            sizes = {len(v) for v in vecs if isinstance(v, list)}
            if not missing and len(sizes) == 1:
                self.kind = "azure"
                self.matrix = np.array(vecs, dtype=np.float32)
            elif missing:
                log.warning("Azure embeddings are configured, but %s of %s opportunities have no vector yet, so matching "
                            "uses local text similarity. Run `python -m app.ingest --embed` to add them.", missing, len(rows))
            else:
                log.warning("Stored opportunity vectors have different sizes (%s), probably from two embedding models, so "
                            "matching uses local text similarity. Run `python -m app.ingest --embed --all` to redo them.",
                            sorted(sizes))
        if self.kind == "tfidf":
            from sklearn.feature_extraction.text import TfidfVectorizer
            from ..agencies import AGENCIES
            corpus = [opportunity_text(r) for r in rows]
            vocab_extra = [a["mission"] + " " + " ".join(a["keywords"]) for a in AGENCIES]
            self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
                                              min_df=1, max_features=60000)
            self.vectorizer.fit(corpus + vocab_extra)
            self.matrix = self.vectorizer.transform(corpus) if corpus else None

    def embed_queries(self, texts: list[str]):
        if self.kind == "azure":
            key = lambda t: hashlib.sha1(t.encode()).hexdigest()  # noqa: E731
            missing = list(dict.fromkeys(t for t in texts if key(t) not in _query_cache))
            if missing:
                vecs = azure_embed(missing)
                if vecs.shape[1] != self.matrix.shape[1]:
                    raise EmbeddingError(f"Deployment '{config.AZURE_EMBEDDING_DEPLOYMENT}' returns {vecs.shape[1]}-number vectors "
                                         f"but the stored ones have {self.matrix.shape[1]} (was the model changed?). "
                                         "Run `python -m app.ingest --embed --all`.")
                for t, v in zip(missing, vecs):
                    _query_cache[key(t)] = v
            return np.stack([_query_cache[key(t)] for t in texts])
        return self.vectorizer.transform(texts)

    def similarities(self, texts: list[str]) -> np.ndarray:
        """Return array (len(texts), n_opportunities) of cosine similarities. With Azure, raises
        EmbeddingError (and starts the cooldown) if the query texts can't be embedded."""
        if not texts or self.matrix is None or not self.ids:
            return np.zeros((len(texts), len(self.ids)))
        try:
            q = self.embed_queries(texts)
        except EmbeddingError as e:
            _trip(e)
            raise
        sims = q @ self.matrix.T
        sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
        return np.clip(sims, 0, 1)


def get_index() -> Index:
    want, version = _wanted(), _version()
    with _lock:
        idx = _indexes.get(want)
        if idx is None or idx.version != version:
            idx = _indexes[want] = Index(want, version)
        return idx
