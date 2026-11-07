"""Vector similarity between opportunities and agency text (mission, strategic plans, projects).

Two interchangeable backends:
  * Azure OpenAI embeddings  - used automatically when AZURE_OPENAI_* + AZURE_EMBEDDING_DEPLOYMENT are set.
                               Opportunity vectors are computed once at ingest and stored.
  * Local TF-IDF             - no keys, no network; good enough for demos and tests.

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

import numpy as np
import requests

from .. import config, db

log = logging.getLogger(__name__)
_lock = threading.Lock()
_index = None
_query_cache: dict[str, np.ndarray] = {}

# Raw cosine -> 0..1 fit. Tuned on the sample set; re-tune with `python -m app.evaluate`.
CALIBRATION = {"tfidf": (0.02, 0.22), "azure": (0.20, 0.55)}


def backend() -> str:
    return "azure" if config.USE_AZURE_EMBEDDINGS else "tfidf"


def calibrate(sim: float) -> float:
    lo, hi = CALIBRATION[backend()]
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
def azure_embed(texts: list[str]) -> np.ndarray:
    url = (f"{config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{config.AZURE_EMBEDDING_DEPLOYMENT}"
           f"/embeddings?api-version={config.AZURE_OPENAI_API_VERSION}")
    vecs = []
    for i in range(0, len(texts), 64):
        r = requests.post(url, headers={"api-key": config.AZURE_OPENAI_KEY},
                          json={"input": [t[:8000] or " " for t in texts[i:i + 64]]}, timeout=60)
        r.raise_for_status()
        vecs.extend(d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"]))
    m = np.array(vecs, dtype=np.float32)
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)


def refresh_opportunity_embeddings() -> None:
    """Called after ingest. Embeds any opportunity that doesn't have a vector yet."""
    global _index
    with _lock:
        _index = None
    if backend() != "azure":
        return
    with db.session() as conn:
        rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM opportunities WHERE embedding IS NULL")]
    if not rows:
        return
    vecs = azure_embed([opportunity_text(r) for r in rows])
    with db.session() as conn:
        for r, v in zip(rows, vecs):
            conn.execute("UPDATE opportunities SET embedding=? WHERE id=?", (json.dumps(v.round(5).tolist()), r["id"]))
    log.info("Embedded %s opportunities with Azure OpenAI", len(rows))


# ---------------- Index ----------------
class Index:
    def __init__(self):
        with db.session() as conn:
            rows = [db.row_to_dict(r) for r in conn.execute("SELECT * FROM opportunities")]
        self.ids = [r["id"] for r in rows]
        self.pos = {oid: i for i, oid in enumerate(self.ids)}
        self.version = db.get_meta("ingest_version")
        self.kind = backend()
        if self.kind == "azure":
            dim = next((len(r["embedding"]) for r in rows if isinstance(r.get("embedding"), list)), 1536)
            self.matrix = np.array([r["embedding"] if isinstance(r.get("embedding"), list) else np.zeros(dim)
                                    for r in rows], dtype=np.float32).reshape(len(rows), dim)
        else:
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
            missing = [t for t in texts if hashlib.sha1(t.encode()).hexdigest() not in _query_cache]
            if missing:
                for t, v in zip(missing, azure_embed(missing)):
                    _query_cache[hashlib.sha1(t.encode()).hexdigest()] = v
            return np.stack([_query_cache[hashlib.sha1(t.encode()).hexdigest()] for t in texts])
        return self.vectorizer.transform(texts)

    def similarities(self, texts: list[str]) -> np.ndarray:
        """Return array (len(texts), n_opportunities) of cosine similarities."""
        if not texts or self.matrix is None or not self.ids:
            return np.zeros((len(texts), len(self.ids)))
        q = self.embed_queries(texts)
        sims = q @ self.matrix.T
        sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
        return np.clip(sims, 0, 1)


def get_index() -> Index:
    global _index
    with _lock:
        if _index is None or _index.version != db.get_meta("ingest_version") or _index.kind != backend():
            _index = Index()
        return _index
