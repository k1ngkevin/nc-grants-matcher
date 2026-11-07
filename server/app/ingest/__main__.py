"""CLI:  python -m app.ingest            live pull from Grants.gov (+ USAspending, + SAM.gov if keyed)
      python -m app.ingest --sample   load the labeled SAMPLE dataset (offline demo / tests)
      python -m app.ingest --max 50   live pull, first 50 records only (quick check)
      python -m app.ingest --sam-check 66.460   test the SAM.gov key + endpoint
      python -m app.ingest --embed    add Azure OpenAI vectors to opportunities that don't have one
                                      (after setting AZURE_EMBEDDING_DEPLOYMENT); --all redoes every one"""
import argparse
import json
import logging
import sys

from . import pipeline, samgov

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
p = argparse.ArgumentParser()
p.add_argument("--sample", action="store_true")
p.add_argument("--max", type=int, default=None)
p.add_argument("--skip-usaspending", action="store_true")
p.add_argument("--sam-check", metavar="ALN")
p.add_argument("--embed", action="store_true", help="embed opportunities that have no Azure OpenAI vector yet")
p.add_argument("--all", action="store_true", help="with --embed: redo every vector (after changing the embedding model)")
a = p.parse_args()
if a.sam_check:
    try:
        print(json.dumps(samgov.lookup(a.sam_check), indent=2))
    except samgov.RateLimited:
        sys.exit("SAM.gov returned 429 Too Many Requests: this key's request limit is used up. Try again later.")
elif a.embed:
    from .. import config, db
    from ..matching import embeddings
    if not config.USE_AZURE_EMBEDDINGS:
        sys.exit("Azure embeddings aren't configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY and "
                 "AZURE_EMBEDDING_DEPLOYMENT (in .env or the environment) first.")
    db.init_db()
    print(f"Embedding with deployment '{config.AZURE_EMBEDDING_DEPLOYMENT}' at {config.AZURE_OPENAI_ENDPOINT}")
    try:
        n = embeddings.refresh_opportunity_embeddings(redo_all=a.all, progress=lambda d, t: print(f"  {d}/{t}", flush=True))
    except embeddings.EmbeddingError as e:
        s = embeddings.vector_status()
        sys.exit(f"Failed: {e}\n{s['with_vector']} of {s['total']} opportunities have a vector. Run this again to continue.")
    s = embeddings.vector_status()
    print(f"Done. Embedded {n}; {s['with_vector']} of {s['total']} opportunities have a vector. "
          "A running server switches to Azure matching on its next search.")
else:
    print(json.dumps(pipeline.run(sample=a.sample, max_records=a.max, skip_usaspending=a.skip_usaspending), indent=2))
