"""CLI:  python -m app.ingest            live pull from Grants.gov (+ USAspending, + SAM.gov if keyed)
      python -m app.ingest --sample   load the labeled SAMPLE dataset (offline demo / tests)
      python -m app.ingest --max 50   live pull, first 50 records only (quick check)
      python -m app.ingest --sam-check 66.460   test the SAM.gov key + endpoint"""
import argparse
import json
import logging

from . import pipeline, samgov

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
p = argparse.ArgumentParser()
p.add_argument("--sample", action="store_true")
p.add_argument("--max", type=int, default=None)
p.add_argument("--skip-usaspending", action="store_true")
p.add_argument("--sam-check", metavar="ALN")
a = p.parse_args()
if a.sam_check:
    print(json.dumps(samgov.lookup(a.sam_check), indent=2))
else:
    print(json.dumps(pipeline.run(sample=a.sample, max_records=a.max, skip_usaspending=a.skip_usaspending), indent=2))
