# NC Federal Funds Matchmaker

A simple website for North Carolina state agencies. Pick your agency and you get the open federal grants you're **eligible for**, **ranked by fit**, each with a **plain-English reason**. Mark each one **Pursue**, **Save for later** or **Dismiss**. You can also get the top matches **by email** daily, weekly, every two weeks or monthly.

It covers 30 NC agencies: cabinet departments, Council of State offices, commissions, the UNC System and the Community College System.

Recommendations default to scores of **50 and above**. Use **Minimum score** above the results to change the cutoff,
or toggle **Include lower scores** to see all scores while keeping your chosen cutoff. The page shows how many lower-scoring
grants are hidden. Your preferences are remembered in this browser; **Reset** restores 50+. Saved, Pursuing and Dismissed grants
remain visible regardless of score. CSV exports and new email subscriptions use the selected score settings.

![NCDOT recommendations with score filtering and AI match previews using live Grants.gov data](docs/screenshot.png)

*NCDOT results showing the minimum-score filter, relevance breakdown, AI previews, and email alerts. Captured November 7, 2026.*

```
Grants.gov ─┐                       ┌─ Guardrails ─┐   ┌─ Blended score ─┐   ┌─ Website (React) ─┐
SAM.gov ────┼─ daily ingest ─ normalize │ expired ✗    ├──▶│ 45 mission/proj │──▶│ filters, triage   │
USAspending ┘                       │ < $50K ✗     │   │ 25 program fit  │   │ CSV export        │
                                    │ ineligible ✗ │   │ 15 eligibility  │   └─ Email digests ───┘
                                    └──────────────┘   │ 10 timing, 5 $  │
                                                       │ ± team feedback │
                                                       └─────────────────┘
```

## Run it (about 2 minutes)

You need Python 3.11+ and Node 18+.

```bash
cd server && pip install -r requirements.txt
```

```bash
cd web && npm install && npm run build
```

```bash
cd server && uvicorn app.main:app --port 8000
```

Open http://localhost:8000. On first start the database is empty, so it loads a clearly labeled **SAMPLE dataset** (yellow "Demo mode" banner, "SAMPLE" tag on each card). Then load live data:

```bash
cd server && python -m app.ingest --max 100
```

That's a quick live check with the first 100 records. Drop `--max` to load everything (a few minutes), and live data replaces the sample set. After that the server re-ingests every day at 6:07 server time.

**Developing the UI:** run the API with `uvicorn app.main:app --reload --port 8000`, then `cd web && npm run dev` and open http://localhost:5173 (calls to `/api` are proxied).

**Tests:** `cd server && python -m pytest -q` (33 tests: guardrails, ranking, triage, email, export).

**Docker:** `docker build -t matchmaker .` then `docker run -p 8000:8000 --env-file .env -v matchmaker-data:/data matchmaker`

## How it meets the blueprint

| Blueprint item | Where | What it does |
|---|---|---|
| Temporal filtering | `server/app/guardrails.py`, `normalize.py` | Drops anything past its close date, re-checked on every search. Categories: **Urgent** (≤14 days), **Standard** (15–60), **60+ days**, **Forecast** |
| $50K financial floor | `guardrails.py` | Uses the award ceiling, otherwise the average award (total ÷ number of awards). Users can raise the floor but not lower it. Grants with no listed amount are kept and flagged, and a checkbox hides them |
| Strict eligibility | `agencies.py`, `guardrails.py` | Grants.gov applicant codes: state agencies need 00 (State governments) or 99 (Unrestricted); the UNC System and community colleges need 06. Code 25 ("Others") is kept at lower weight. Checked **before** scoring |
| Multi-source | `ingest/` | Grants.gov `search2` + `fetchOpportunity` (posted and forecasted) · SAM.gov Assistance Listings (program objectives, optional key) · USAspending (how much NC received under each program last fiscal year) |
| Strategic plans | "Improve your matches" panel → `agency_documents` | Paste or upload plan text. It's split into chunks and embedded, and the best-matching chunk counts toward mission fit |
| Project intake | same panel → `projects` | Staff log active projects. A grant that fits a project gets a boost and names the project in its explanation |
| Blended score | `matching/score.py` | 45 mission + project similarity · 25 program fit (an Assistance Listing the agency usually receives + keywords) · 15 eligibility · 10 timing · 5 award size · ± feedback. Every part is shown under "Details & how it was scored" |
| Explanations | `matching/explain.py` | Rule-based by default (instant, free). With Azure OpenAI configured, the first 5 results per page get AI previews grounded in the listing, agency/project/plan context and score breakdown. Cached by the prompt, context, score and deployment |
| Pursue / Save / Dismiss | `GrantCard.jsx`, `POST /api/decisions` | Pursue can email the opportunity and a note to the grant-writing team. Dismiss asks for a reason (e.g. "Can't meet the match"), and those reasons adjust future scores for that agency |
| Human decides | throughout | Nothing is auto-applied. Scores are labeled as recommendations |
| precision@10 | `app/evaluate.py`, `GET /api/metrics` | Computed from real Pursue/Save/Dismiss labels |
| Export | "Download CSV" | Current view with scores and reasons |
| Email alerts | `emailer.py` | Double opt-in, daily/weekly/biweekly/monthly, top 5–25, uses the filters set at signup, one-click unsubscribe, optional domain allow-list |

The card preview separates mission/program relevance (70 possible points) from eligibility, timing and award size (30).
The additive score and ranking stay the same. A **Good match** label needs a total of at least 50, at least 18/45 semantic points,
and 35/70 relevance points. **Strong match** needs 70 total, 27/45 semantic and 49/70 relevance points. Otherwise the label is
**Possible match**, including high totals driven by practical factors or feedback. These screening thresholds still need validation
with agency reviewers; text similarity can overstate substantive relevance.

AI previews receive the score, component points, matching mission/plan excerpt, project details and listing facts. They use scoring
evidence as background and describe the grant's fit, limitations and next check without repeating score arithmetic. They flag domain
mismatches even when the computed label is optimistic. Empty project lists are treated
as missing context. Explanations are cached by their exact prompt/context/score and chat deployment, so old summaries are
replaced on demand when those inputs change; existing rows do not need to be deleted or migrated.

### Azure (optional; everything works without it)

| Set these | What changes |
|---|---|
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_EMBEDDING_DEPLOYMENT` | Similarity switches from local TF-IDF to Azure OpenAI embeddings once every opportunity has a vector. Vectors are computed at ingest; for data loaded before you set these, run `cd server && python -m app.ingest --embed`. If Azure fails (wrong deployment name, bad key), matching falls back to TF-IDF and the server log says why. Re-tune `CALIBRATION` in `matching/embeddings.py` for your embedding model |
| `AZURE_CHAT_DEPLOYMENT` | AI-written match previews for the first 5 results per page and in emails |
| `ACS_CONNECTION_STRING` | Real email through the Azure Communication Services email API, using the connection string from the resource's Keys page. No SMTP login or Entra app needed. Set `SMTP_FROM` to the email domain's MailFrom address. ACS Email is being retired September 30, 2028 |
| `SMTP_*` | Real email through SendGrid, Azure Communication Services (being retired September 30, 2028) or any SMTP relay. Microsoft is retiring password sign-in for SMTP in Exchange Online, so check with IT before using an Office 365 mailbox. Without it, emails go to `server/data/outbox/`. Test the settings with `cd server && python -m app.emailer you@agency.nc.gov` |
| `SAM_API_KEY` | SAM.gov program descriptions are added to the matching text |

See `.env.example` for every setting. Copy it to `.env` in the repo root and the server reads it on startup (real environment variables win). With Docker, use `--env-file`.

**Deploy (Lane A):** push the image to Azure Container Registry, then run it on Azure Container Apps with one replica and an Azure Files volume mounted at `/data`. The daily ingest and email scheduler run inside the app. Put it behind Entra ID sign-in (Container Apps "Authentication") so only state staff can reach it.

## Team lanes: what's done and what's next

- **Lane A, Cloud & Ops.** Done: Dockerfile, env-based config, in-app daily scheduler. Next: create the Azure resource group, Container Registry, Container App, Azure OpenAI deployments and Entra ID auth. For production, move SQLite → Azure Database for PostgreSQL and the in-memory vector index → Azure AI Search (same inputs/outputs; see `matching/embeddings.py`).
- **Lane B, Data & Ingestion.** Done: Grants.gov, USAspending and SAM.gov connectors, normalization, and 30 agency profiles in `server/app/agencies.py`. Next: **run the live ingest and check the parsed fields** (see the caveats below), have each agency confirm its mission summary and typical programs (Assistance Listing prefixes), and load real strategic plans.
- **Lane C, Matching & AI.** Done: blended scoring, feedback loop, explanation prompt, precision@10. Next: label 20–30 grants for 3–4 agencies, run `python -m app.evaluate`, then tune `WEIGHTS` / `CALIBRATION`.
- **Lane D, App & Story.** Done: the site, triage, CSV, email signup and preview, glossary. Next: the pitch (outline below) and a usability check with a real grants coordinator.

## Honest caveats

- **Live APIs are untested from our build machine.** Its network blocked api.grants.gov and api.usaspending.gov. The Grants.gov parser was written against the documented response shape and reads fields defensively, but run `python -m app.ingest --max 50` first and check the results. The **SAM.gov endpoint is the least certain**; check it with `python -m app.ingest --sam-check 66.460`, and set `SAM_ASSISTANCE_URL` if it differs.
- **The sample dataset is invented** (numbers start with `SAMPLE-`). It's for demos and tests only.
- **Agency mission summaries and program lists were written by the team** from public descriptions. Have each agency correct them.
- **No login in the app itself.** Put it behind Entra ID before real use. All data is public federal grant data plus whatever projects and plans agencies type in.

## 6-minute pitch outline

1. **The problem (45s).** Grant-finding depends on whoever has time. At DNCR, one person checks Grants.gov by hand. Grants.gov isn't complete, eligibility is buried, and agencies miss money.
2. **The idea (30s).** Pick your agency and get only the grants you can win, ranked and explained. Or let them come to your inbox.
3. **Live demo (2.5 min).** Pick DEQ and see the urgent PFAS grant on top with its reason → open "how it was scored" → add an active project and watch the matching grant move up and name it → Pursue, which emails the grant team → Dismiss with "can't meet match" → subscribe to the weekly email and show the email.
4. **Trust (45s).** Four guardrails (expired, under $50K, ineligible, single-source) · transparent score · humans decide · public data only, Entra ID sign-in, double opt-in email (for the IT and cybersecurity judges).
5. **Scale and next steps (1 min).** Already covers 30 agencies. Azure deployment plan · precision@10 from real decisions · the NC past-funding signal from USAspending · ask agencies to load their strategic plans.
