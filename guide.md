# Development Guide

Step-by-step plan to build Scout AI. For the product vision, competitors and roadmap, see [README.md](README.md).

Each step ends with a **Done when** check. Don't move on until it passes.

---

## Proposed stack

The repository is empty, so these are defaults, not decisions. Change them before Step 1 if the team prefers something else.

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.14 | Best ecosystem for scraping, data and LLM work |
| Dependency management | `uv` | Fast, single lockfile |
| Scraping | `httpx` + `selectolax`; `playwright` only for JS-heavy pages | Light by default, browser only when needed |
| Storage | PostgreSQL (SQLite for local dev) | Relational data, served to the web dashboard through the API |
| Demo data | Parquet (`pyarrow`) + `Faker`; synthetic dataset committed under `data/demo/` | The project is a demo shown to a wide audience: share realistic data through Git without exposing real HubSpot/ClickUp records (Step 5) |
| ORM / migrations | SQLAlchemy + Alembic | Standard, well-documented |
| LLM | Claude Agent SDK, authenticated with the Claude subscription (no API key) | Summaries: `claude-sonnet-5-5`; recommendations: `claude-opus-5-5` |
| Scheduling | Cron / GitHub Actions to start; a job queue later if needed | Keep the MVP simple |
| Dashboard | FastAPI (API) + JavaScript web front end | Read-only view over the Postgres tables; see Step 10 |
| Tests / quality | `pytest`, `ruff`, `mypy` | |

---

## Step 0 — Discovery (before writing code)

1. **Confirm data access.**
   - HubSpot: create a **Private App** with read scopes for contacts, companies, deals and marketing campaigns.
   - ClickUp: generate an API token and pick the Space whose marketing tasks `scout fetch` will read (Step 5).
2. **Audit HubSpot data quality.**
   - Are `original source`, campaign and lifecycle stage filled in consistently?
   - Is there a **competitor** property on deals? If not, create it (dropdown: LabVantage, LabWare, Clinisys, STARLIMS, CloudLIMS, Other, None) and ask Sales to fill it from now on.
3. **Validate the competitor list** using won/lost deals (see README §3).
4. **Agree on the first users** (who on Marketing reads the weekly summary) and the delivery channel (email, Teams, ClickUp doc).

**Done when:** credentials work, the competitor field exists, and the top 3 list is confirmed with data.

---

## Step 1 — Project setup

1. Create a Python 3.14 virtual environment and install dependencies from `requirements.txt` (runtime) and `requirements-dev.txt` (tests and quality):
   ```bash
   uv venv --python 3.14
   uv pip install -r requirements-dev.txt
   playwright install chromium   # only if a collector needs a browser
   ```
2. Create the folder structure:
   ```
   src/scout_ai/
     config.py          # settings loaded from environment
     db/                # models and session
     collectors/        # one module per external source
     integrations/      # hubspot.py, clickup.py (read-only API clients)
     demo/              # synthesize.py (real patterns -> synthetic tables), load.py
     analysis/          # LLM summarization and recommendations
     reports/           # weekly summary rendering
     cli.py             # entry points: db-setup, collect, fetch, load, analyze, report
   data/demo/           # synthetic Parquet dataset, committed to Git (Step 5)
   tests/
   ```
3. Add `.env.example` with every variable the app needs (no real values):
   ```
   DATABASE_URL=
   CLAUDE_CODE_OAUTH_TOKEN=   # only for unattended runs; locally use `claude login`
   HUBSPOT_TOKEN=             # only on the machine that runs `scout fetch`
   CLICKUP_TOKEN=             # only on the machine that runs `scout fetch`
   DEMO_SEED=42               # change it to generate a different synthetic dataset
   ```
4. Configure `ruff`, `mypy` and `pytest` in `pyproject.toml`, and add a CI workflow that runs them.

**Done when:** `uv run pytest` and `uv run ruff check` pass in CI on an empty project.

---

## Step 2 — Data model

Create these tables with Alembic migrations:

| Table | Purpose | Key fields |
|---|---|---|
| `competitors` | Who we track | name, website, tier (`top3` / `watchlist`) |
| `sources` | What we collect per competitor | competitor_id, type (homepage, blog, events, press, jobs, reviews), url, frequency |
| `snapshots` | Raw captured content | source_id, fetched_at, content_hash, raw_text |
| `signals` | Meaningful changes extracted from snapshots | competitor_id, type, title, summary, url, detected_at |
| `funnel_metrics` | Internal data by channel/campaign/period | period, channel, campaign, leads, mqls, sqls, opportunities, deals_won, revenue |
| `deals_competition` | Deals where a competitor was involved | deal_id, competitor_id, outcome, amount, closed_at |
| `initiatives` | Marketing initiatives read from ClickUp (Steps 5 and 7) | title, status, channel, campaign, started_at, completed_at |
| `recommendations` | AI output | action, evidence (JSON with links), impact, cost, effort, confidence, priority, status, clickup_task_id |

`initiatives` is not in the initial migration yet; add it with a new Alembic revision before building `scout load`.

**Done when:** migrations run on a clean database and a seed script inserts the five competitors with their sources.

How to run it locally (models in `src/scout_ai/db/models.py`, migrations in `src/scout_ai/db/migrations/`):

```bash
docker compose -f docker/compose.yml up -d --build   # PostgreSQL 18 on localhost:5434
# DATABASE_URL=postgresql+psycopg://scout:scout@localhost:5434/scout_ai  (see .env.example)
scout db-setup                                        # create database, migrate, seed (idempotent)
alembic revision --autogenerate -m "describe change"  # after changing a model
```

---

## Step 3 — Competitor collectors

1. Write one collector per source type in `collectors/`, all sharing one interface: `fetch(source) -> Snapshot`.
2. Rules for every collector:
   - Check `robots.txt` and the site's terms of use; skip sources that disallow it.
   - Identify the bot in the `User-Agent`, rate-limit requests and cache responses.
   - Prefer RSS feeds, sitemaps and official APIs over HTML parsing.
3. **Change detection:** store a hash of the cleaned text; only create a new snapshot when the hash changes.
4. Start with the sources that matter most, in this order: homepage and segment pages → blog/news → events/webinars → press releases → job postings → G2/Capterra reviews.
5. Add a CLI command: `uv run scout collect`.

**Done when:** running `collect` twice in a row creates snapshots the first time and none the second time (no changes), and each collector has tests using saved HTML fixtures.

---

## Step 4 — Signal extraction with the LLM

1. For each new snapshot, send the **diff** against the previous snapshot (not the whole page) to `claude-sonnet-5-5`.
2. Ask for structured output (JSON validated by a Pydantic model): signal type, title, 2–3 sentence summary, relevance to myLIMS segments, and the source URL.
3. Discard snapshots where the model reports no meaningful change.
4. Store the prompt version with each signal so results are reproducible.
5. Build a small **evaluation set** (20–30 real diffs labeled by Marketing) and check precision before trusting the output.

**Done when:** at least 80% of signals in the evaluation set are judged useful by the Marketing team.

---

## Step 5 — Internal data: synthetic demo dataset

Scout AI is a demo that will be presented to a wide audience, so the database never holds real HubSpot or ClickUp records. One person runs `scout fetch`, which reads the real data, learns its patterns and writes a **synthetic** dataset to `data/demo/`. That dataset is committed to Git, and anyone fills their database with `scout load`.

```
scout fetch (needs tokens)                                            scout load (anyone)
HubSpot + ClickUp -> memory -> synthesize -> data/demo/*.parquet -> git push -> git pull -> Postgres
```

1. **Read** (`integrations/hubspot.py`, `integrations/clickup.py`):
   - HubSpot: deals (stage, amount, create and close dates, source, campaign, competitor property) and contacts' lifecycle stages, through the CRM v3 API. Do not request names, emails or phone numbers.
   - ClickUp: marketing tasks (name, status, dates, tags) to see which initiatives ran and how long they took.
   - Real records stay in memory only: nothing real is written to disk, logs or the database.
2. **Synthesize** (`demo/synthesize.py`), with a fixed seed (`DEMO_SEED`) so the same input always gives the same output:
   - Companies, contacts, deal owners and task assignees: plausible fake names from `Faker` (`pt_BR`), never derived from the real ones.
   - Amounts: sampled from the real distribution (range, median, long tail), not copied.
   - Stages, channels, campaigns, competitor mix and win rates: same proportions as the real data, with noise.
   - Dates: same period, keeping the order (created → closed; task started → completed).
   - Competitor names stay real, since they are the subject of the project; deal outcomes against each one are sampled.
   - Groups with fewer than 10 real records (e.g. a rare competitor or campaign) are merged or smoothed, so the synthetic numbers cannot reproduce the real ones.
   - Aggregate into the shape of the tables: `funnel_metrics` per channel, campaign and month; `deals_competition`; `initiatives`.
3. **Write** one Parquet file per table to `data/demo/` (`funnel_metrics.parquet`, `deals_competition.parquet`, `initiatives.parquet`) plus `manifest.json` (generated_at, seed, row counts, generator version). Competitors are referenced by name and resolved to IDs on load; deal IDs are synthetic (`demo-0001`, …).
4. **Share:** commit `data/demo/` and push. The repository is private and the dataset is synthetic, so it is safe there. Never commit real API responses; `.gitignore` ignores everything under `data/` except `data/demo/`.
5. **Load** (`demo/load.py`): read `data/demo/`, check it against `manifest.json`, and replace the content of the internal-data tables in one transaction. Idempotent: running it twice gives the same database. Needs only `DATABASE_URL`, no tokens.
6. Add CLI commands `uv run scout fetch` and `uv run scout load`; they replace the planned `scout sync`.

**Done when:** on a clean machine, `git pull`, `scout db-setup` and `scout load` produce the same tables as on the machine that ran `fetch`; the synthetic funnel conversion rates and win rates per competitor are within ±5 percentage points of the real ones (`fetch` prints this comparison, without the real values themselves going to disk); and no real company, person or deal ID appears in `data/demo/`.

---

## Step 6 — Weekly summary (first user-facing output)

1. Generate a report with:
   - New signals per competitor this week
   - Funnel snapshot: leads → opportunities → deals by channel, versus the previous period
   - Deals won/lost against each competitor
2. Render as Markdown/HTML and deliver through the channel chosen in Step 0.
3. Schedule `collect → load → report` weekly. Rerun `fetch` only when the demo dataset should reflect newer real patterns.
4. Label the summary as built on synthetic demo data.
5. Collect feedback from readers for 3–4 weeks and adjust.

**Done when:** the Marketing team reads the summary every week and has used it at least once to make a decision.

---

## Step 7 — Recommendations engine

1. Build the context for `claude-opus-5-5`: recent signals, funnel metrics, competitive deal outcomes and recent ClickUp initiatives.
2. Ask for 3–5 recommendations, each with: action, evidence (signal IDs + metrics, with links), and 1–5 scores for impact, cost, effort and confidence.
3. Compute priority in code, not in the prompt: `impact × confidence ÷ (cost + effort)`.
4. Reject any recommendation whose evidence does not reference real stored records.
5. Add the top recommendations to the weekly summary.

In the demo, recommendations are built on synthetic internal data: they show that the system works, not what the business should do.

**Done when:** every recommendation links to verifiable evidence and Marketing approves at least one per month.

---

## Step 8 — Close the loop

1. When a recommendation is approved, create a ClickUp task with the action, evidence and scores; store the `clickup_task_id`.
2. Tag the related HubSpot campaign so results can be traced back.
3. After the task is completed, compare funnel metrics before and after and record the outcome on the recommendation.
4. Feed past outcomes back into the recommendation prompt so the system learns what works.

In the demo, items 1 and 2 run as a **dry run**: log the ClickUp task and HubSpot tag that would be created instead of calling the APIs, so synthetic recommendations never become real tasks. Items 3 and 4 need real data and come after the demo.

**Done when:** we can show, for each executed recommendation, its measured effect on leads, opportunities or deals.

---

## Step 9 — Operate and harden

- **Monitoring:** log every job run; alert on failed collectors (sites change their layout often).
- **Costs:** track LLM token usage per job; cache unchanged inputs.
- **Security:** keep tokens in a secrets manager, never in the repo; only the machine that runs `scout fetch` needs them. Give integrations read-only scopes except ClickUp task creation.
- **Privacy:** real HubSpot and ClickUp records never leave memory during `fetch`; only the synthetic dataset is stored and committed (Step 5).
- **Dashboard:** protect the web dashboard (Step 10) with company login; never expose the database directly.

---

## Step 10 — Web dashboard

The dashboard is our own web app, not a BI tool. It shows what the weekly summary shows, with filters and history, and lets Marketing act on recommendations. It does not try to replace HubSpot's own reports (README §4 and §7).

1. **API** (`src/scout_ai/api/`, FastAPI): read-only endpoints over the existing tables, e.g. `GET /competitors`, `GET /signals?competitor=&type=&since=`, `GET /funnel?from=&to=&channel=`, `GET /deals/competition`, `GET /recommendations?status=`. The only write is `PATCH /recommendations/{id}` to approve or reject one, which triggers the ClickUp task from Step 8.
2. **Front end** (`web/`): a JavaScript single-page app consuming the API. Views:
   - Signals feed per competitor (new this week, by type, with links to the source)
   - Funnel by channel and campaign: leads → opportunities → deals won, versus the previous period
   - Win/loss against each competitor
   - Recommendations ranked by priority, with evidence links and approve/reject buttons
3. **Auth:** company single sign-on (Microsoft Entra ID) in front of both the API and the front end. The API connects to Postgres with a read-mostly database role.
4. **Deploy:** the API and front end as containers next to the Postgres from `docker/`; add them to `docker/compose.yml` for local development.
5. **Demo label:** show a visible "synthetic demo data, generated from real patterns" banner on every view.

**Done when:** Marketing uses the dashboard instead of the emailed summary for at least one weekly review, and approving a recommendation there creates its ClickUp task (dry run in the demo).

---

## Definition of done for the MVP

- [ ] Top 3 competitors monitored automatically every week
- [ ] Synthetic demo dataset generated from HubSpot/ClickUp patterns, shared through Git and loaded with `scout load`
- [ ] Weekly summary delivered and used by Marketing
- [ ] Recommendations with evidence and scores, turned into ClickUp tasks (dry run in the demo)
- [ ] Web dashboard (FastAPI + JavaScript) live for Marketing
- [ ] At least one recommendation executed and its impact measured (after the demo, with real data)
