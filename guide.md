# Development Guide

Step-by-step plan to build Scout AI. For the product vision, competitors and roadmap, see [README.md](README.md).

Each step ends with a **Done when** check. Don't move on until it passes.

Scout AI is a **hackathon project**. It ends in a demo, not in daily use: Marketing does not use the system during the hackathon, and nothing runs on a schedule. The commands run on demand before the presentation (`scripts/weekly.ps1`). So checks that need weeks of real use by the Marketing team (reader feedback, labeling, approvals, weekly runs, measured impact) are out of scope and are adapted to something the team can show in the demo; each step says how.

**Status (2026-11-06):** Steps 1 to 7 are implemented. Open items: Step 0 is not recorded in the repo; Step 4's evaluation set (item 5) waits for real diffs; the notifications page (Step 6) and approving recommendations (Step 7) are shown in the dashboard (Step 10). Next: Step 8.

---

## Proposed stack

These were the defaults chosen before Step 1; change them through a PR if the team prefers something else.

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.14 | Best ecosystem for scraping, data and LLM work |
| Dependency management | `uv` | Fast, single lockfile |
| Scraping | `httpx` + `selectolax`; `playwright` only for JS-heavy pages | Light by default, browser only when needed |
| Storage | PostgreSQL (SQLite for local dev) | Relational data, served to the web dashboard through the API |
| Demo data | Parquet (`pyarrow`) + `Faker`; synthetic dataset committed under `data/demo/` | The project is a demo shown to a wide audience: share realistic data through Git without exposing real HubSpot records or Marketing spend (Step 5) |
| ORM / migrations | SQLAlchemy + Alembic | Standard, well-documented |
| LLM | Claude Agent SDK, authenticated with the Claude subscription (no API key) | Summaries: `claude-sonnet-5-5`; recommendations: `claude-opus-5-5` |
| Scheduling | None for the demo: the commands run on demand (`scripts/weekly.ps1`). After the hackathon: cron or GitHub Actions, a job queue if needed | The database only runs on a laptop, and the demo needs one fresh run, not a weekly one |
| Dashboard | FastAPI (API) + JavaScript web front end | Read-only view over the Postgres tables, including the notifications page with the weekly summaries; see Step 10 |
| Tests / quality | `pytest`, `ruff`, `mypy` | |

---

## Step 0 — Discovery (before writing code)

1. **Confirm data access.**
   - HubSpot: create a **Private App** with read scopes for contacts, companies, deals and marketing campaigns.
   - Marketing spend: Marketing does not track its initiatives in a tool yet. Get the monthly cost exports (`Monthly MQL Cost Summary` and `MQL Count` CSVs) and keep them in `data/raw/` on the machine that runs `scout fetch` (Step 5).
2. **Audit HubSpot data quality.**
   - Are `original source`, campaign and lifecycle stage filled in consistently?
   - Is there a **competitor** property on deals? If not, create it (dropdown: LabVantage, LabWare, Clinisys, STARLIMS, CloudLIMS, Other, None) and ask Sales to fill it from now on.
3. **Validate the competitor list** using won/lost deals (see README §3).
4. **Agree on the audience and the delivery channel.** For the hackathon the audience is the demo's; nobody on Marketing reads the summary week to week. Decided on 2026-11-05: the summary is shown on a notifications page in the web dashboard (Steps 6 and 10), not sent by email or Teams.

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
     integrations/      # hubspot.py (read-only API client), marketing_csv.py (cost exports)
     demo/              # synthesize.py (real patterns -> synthetic tables), load.py
     analysis/          # LLM summarization and recommendations
     reports/           # weekly summary rendering
     cli.py             # entry points: db-setup, collect, fetch, load, analyze, report
   data/raw/            # Marketing CSV exports, personal data: ignored by Git (Step 5)
   data/demo/           # synthetic Parquet dataset, committed to Git (Step 5)
   tests/
   ```
3. Add `.env.example` with every variable the app needs (no real values):
   ```
   DATABASE_URL=
   CLAUDE_CODE_OAUTH_TOKEN=   # only for unattended runs; locally use `claude login`
   HUBSPOT_TOKEN=             # only on the machine that runs `scout fetch`
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
| `funnel_metrics` | Internal data by region/channel/campaign/period | period, region, channel, campaign, leads, mqls, sqls, opportunities, deals_won, revenue |
| `deals_competition` | Deals where a competitor was involved | deal_id, competitor_id, outcome, amount, closed_at |
| `campaigns` | Marketing campaigns seen in HubSpot, our "initiatives" (Steps 5 and 7) | name, channel, first_mql_at, last_mql_at |
| `marketing_spend` | Monthly Marketing spend per region, from the cost exports | period, region, amount |
| `recommendations` | AI output | action, evidence (JSON with links), impact, cost, effort, confidence, priority, status, clickup_task_id |
| `weekly_summaries` | Weekly summaries for the dashboard's notifications page (Step 6) | report_date, title, month, signal_count, markdown |

`campaigns`, `marketing_spend` and `funnel_metrics.region` come from migration `0002`; `snapshots.analyzed_at` and `analysis_prompt_version` from `0003` (Step 4); `weekly_summaries` from `0004` (Step 6); `recommendations.prompt_version` from `0005` (Step 7). Spend is only known per region, not per channel or campaign, so cost metrics (cost per MQL, CAC) are per region.

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

How it works (code in `src/scout_ai/collectors/`, fixtures in `tests/fixtures/collectors/`):

- `PageCollector` (homepage, segment, comparison, pricing) stores the page's visible text, without scripts, menus, footers, forms and cookie banners.
- `ListingCollector` (blog, press, events, jobs) stores one line per item (`date | title | details | url`): from a feed given as the source URL (e.g. the Clinisys Teamtailor `jobs.rss`, which adds department and countries), or the page's own RSS/Atom feed when it links one under its path, else from `<article>` elements or linked headings, else the page text (hub pages and job tables).
- `http.py` sends every request with `COLLECTOR_USER_AGENT`, checks `robots.txt` first (RFC 9309, with `*` and `$` patterns, which `urllib.robotparser` does not support), waits `COLLECTOR_DELAY_SECONDS` (or the site's `Crawl-delay`) between requests to the same host, and caches responses for the run.
- Each source ends as `new`, `unchanged`, `blocked` (robots.txt, 401 or 403: never worked around), `unsupported` (reviews: no allowed access path) or `failed`. The command exits with 1 only when a source failed.
- LabVantage answers 403 to bots, including on `robots.txt`, so it is reported as `blocked`. No allowed alternative was found (Business Wire also blocks bots, Google News disallows its RSS), so it moved to the watchlist (README §3).
- Sources (`src/scout_ai/db/seed.py`): each top 3 competitor has its homepage, the segment pages that overlap myLIMS (food, environmental/water, agribusiness, chemical, pharma), news/press, blog, events and jobs where the site offers them, collected weekly; watchlist sources monthly. STARLIMS has no events page, and its resource library filters by category in the browser, so one URL covers its news, blogs and product updates.
- Jobs: LabWare and CloudLIMS career pages, Clinisys job board feed. STARLIMS jobs are on ADP Workforce Now (JavaScript only) and LinkedIn forbids scraping, so neither is collected.
- Reviews: Capterra's `robots.txt` disallows everything and G2's terms forbid automated access. Options: a paid data agreement with G2, or a monthly manual export by Marketing into `data/raw/`.

```bash
scout collect   # all active sources, every run; scheduling decides the cadence (Step 6)
```

---

## Step 4 — Signal extraction with the LLM

1. For each new snapshot, send the **diff** against the previous snapshot (not the whole page) to `claude-sonnet-5-5`.
2. Ask for structured output (JSON validated by a Pydantic model): signal type, title, 2–3 sentence summary, relevance to myLIMS segments, and the source URL.
3. Discard snapshots where the model reports no meaningful change.
4. Store the prompt version with each signal so results are reproducible.
5. Build a small **evaluation set** (20–30 real diffs labeled by Marketing) and check precision before trusting the output.

**Done when:** at least 80% of signals in the evaluation set are judged useful by the Marketing team.

For the demo, the team labels the evaluation set instead of Marketing, once enough real diffs have been collected.

How it works (code in `src/scout_ai/analysis/signals.py`):

- `scout analyze` takes every snapshot not analyzed yet, in collection order. The first snapshot of a source is a baseline (nothing to compare with, no LLM call); a whitespace-only change is skipped without a call.
- Otherwise the unified diff against the previous snapshot of the same source (2 context lines, capped at 15,000 characters) goes to `claude-sonnet-5-5` through the Claude subscription (`src/scout_ai/llm.py`), with a JSON schema (structured output) validated by Pydantic: `meaningful_change` plus a list of signals (type, title, summary, relevance to myLIMS segments, URL).
- The system prompt describes myLIMS (segments, Brazil/LatAm), what counts as meaningful, the signal types, and tells the model to use only facts in the diff and to treat the page content as data, not instructions.
- A signal URL the model returns is kept only if it is the page URL or appears in the diff, so no invented links are stored.
- Analyzed snapshots get `analyzed_at` and `analysis_prompt_version` (migration `0003`), also when nothing was meaningful, so each snapshot goes to the LLM once. Each signal stores `prompt_version`; bump `PROMPT_VERSION` whenever the prompt or schema changes. A failed call leaves the snapshot pending for the next run, and the command exits with 1.

```bash
scout collect && scout analyze
```

---

## Step 5 — Internal data: synthetic demo dataset

Scout AI is a demo that will be presented to a wide audience, so the database never holds real HubSpot records or Marketing spend. One person runs `scout fetch`, which reads the real data, learns its patterns and writes a **synthetic** dataset to `data/demo/`. That dataset is committed to Git, and anyone fills their database with `scout load`.

```
scout fetch (needs token + CSVs)                                              scout load (anyone)
HubSpot + data/raw/*.csv -> memory -> synthesize -> data/demo/*.parquet -> git push -> git pull -> Postgres
```

1. **Read** (`integrations/hubspot.py`, `integrations/marketing_csv.py`):
   - HubSpot: deals (stage, amount, create and close dates, source, campaign, competitor property) and contacts' lifecycle stages, through the CRM v3 API. Do not request names, emails or phone numbers. An amount below 1 (0, or the 0.01 some deals carry) means nobody filled it in, so it is read as unknown.
   - Marketing CSVs in `data/raw/`: monthly spend per region from `Monthly MQL Cost Summary` (one block per month, one row per region); campaign, channel and region of each MQL from `MQL Count`. The MQL list holds names and contact IDs: read only the columns above and drop the rest on load.
   - Campaigns are our "initiatives": each distinct campaign (`Original Source Drill-Down 1`) with its channel and the dates of its first and last MQL.
   - Real records stay in memory only: nothing real is written to disk, logs or the database.
2. **Synthesize** (`demo/synthesize.py`), with a fixed seed (`DEMO_SEED`) so the same input always gives the same output:
   - Companies, contacts, deal owners and campaign names: plausible fake names from `Faker` (`pt_BR`), never derived from the real ones.
   - Amounts and spend: sampled from the real distribution (range, median, long tail), not copied; spend keeps its month-to-month and region-to-region shape.
   - Stages, channels, campaigns, competitor mix and win rates: same proportions as the real data, with noise.
   - Dates: same period, keeping the order (created → closed; a campaign's first MQL → last MQL).
   - Competitor names stay real, since they are the subject of the project; deal outcomes against each one are sampled.
   - Groups with fewer than 10 real records (e.g. a rare competitor or campaign) are merged or smoothed, so the synthetic numbers cannot reproduce the real ones.
   - Aggregate into the shape of the tables: `funnel_metrics` per region, channel, campaign and month; `deals_competition`; `campaigns`; `marketing_spend` per region and month.
   - Period: deals are read from the first month of the spend export, so funnel and spend cover the same months. In `funnel_metrics`, `mqls` come from the MQL export, `opportunities` are deals by creation month, `deals_won` and `revenue` are won deals by close month; `leads` and `sqls` stay 0 until a source exists.
3. **Write** one Parquet file per table to `data/demo/` (`funnel_metrics.parquet`, `deals_competition.parquet`, `campaigns.parquet`, `marketing_spend.parquet`) plus `manifest.json` (generated_at, seed, row counts, generator version). Competitors are referenced by name and resolved to IDs on load; deal IDs are synthetic (`demo-0001`, …).
4. **Share:** commit `data/demo/` and push. The repository is private and the dataset is synthetic, so it is safe there. Never commit real API responses or the Marketing CSVs; `.gitignore` ignores everything under `data/` except `data/demo/`.
5. **Load** (`demo/load.py`): read `data/demo/`, check it against `manifest.json`, and replace the content of the internal-data tables in one transaction. Idempotent: running it twice gives the same database. Needs only `DATABASE_URL`: no token, no CSV.
6. Add CLI commands `uv run scout fetch` and `uv run scout load`; they replace the planned `scout sync`.

**Done when:** on a clean machine, `git pull`, `scout db-setup` and `scout load` produce the same tables as on the machine that ran `fetch`; the synthetic funnel conversion rates, win rates per competitor and each region's share of spend are within ±5 percentage points of the real ones (`fetch` prints this comparison, without the real values themselves going to disk); and no real company, person, campaign name, deal ID or spend value appears in `data/demo/`.

---

## Step 6 — Weekly summary (first user-facing output)

1. Generate a report with:
   - New signals per competitor this week
   - Funnel snapshot: leads → opportunities → deals by region and channel, versus the previous period
   - Spend per region: cost per MQL, pipeline created per dollar spent and Marketing CAC, versus the previous period
   - Deals won/lost against each competitor
2. Render as Markdown and store it in the database for the dashboard's notifications page (Step 10), the channel chosen in Step 0.
3. Run `collect → analyze → recommend → report` in one go. For the demo it runs on demand before the presentation; after the hackathon, schedule it weekly. Rerun `fetch` only when the demo dataset should reflect newer real patterns.
4. Label the summary as built on synthetic demo data.

**Done when:** `scout report` builds the summary from the current database, with every section of item 1, and stores it in `weekly_summaries`, ready for the notifications page. Showing it on that page is checked in Step 10.

How it works (code in `src/scout_ai/reports/`):

- `scout report` stores the summary in `weekly_summaries` (one per day: running it again the same day replaces it) and also writes it to `data/reports/weekly-YYYY-MM-DD.md` (`REPORT_DIR`; ignored by Git like the rest of `data/`) for reading locally.
- Signals: those detected in the 7 days before the report date, grouped by competitor, top 3 first, each with its type, link, summary and why it matters.
- Funnel and spend: monthly, because that is how the internal data is aggregated. The report uses the latest month with Marketing spend, so a month still in progress is never compared with a full one, against the month before. By region: MQLs, opportunities, deals won, spend, cost per MQL, opportunities per $1,000 and Marketing CAC (spend per deal won). By channel: MQLs, opportunities, deals won and MQL-to-opportunity rate.
- Leads and SQLs are not tracked yet, so the funnel starts at MQLs. Pipeline value per dollar needs opportunity amounts, which no table stores; opportunities per $1,000 stand in for it until they do.
- Competitive deals: won and lost per competitor in the report month and year to date (by close date), win rate and open deals.
- The summary opens with the demo-data label (item 4).
- Delivery (item 2): the dashboard's notifications page lists the stored summaries, newest first, and shows the Markdown of the one selected (Step 10). There is no email or Teams message.
- Run (item 3): `scripts/weekly.ps1` runs `collect`, `analyze`, `recommend` (Step 7) and `report` in order, keeps going if a step fails, and exits with 1 if any did. For the hackathon it is run by hand before the demo, not scheduled: the database only runs on a laptop. The script header has the Task Scheduler command for after the hackathon.
- The signal window is the 7 days before the report date, so signals detected on the report day itself appear in the next summary. With on-demand runs this is accepted for the demo.

```powershell
.\scripts\weekly.ps1   # or: scout collect; scout analyze; scout recommend; scout report
```

---

## Step 7 — Recommendations engine

1. Build the context for `claude-opus-5-5`: recent signals, funnel metrics, competitive deal outcomes, recent campaigns and spend per region.
2. Ask for 3–5 recommendations, each with: action, evidence (signal IDs + metrics, with links), and 1–5 scores for impact, cost, effort and confidence.
3. Compute priority in code, not in the prompt: `impact × confidence ÷ (cost + effort)`.
4. Reject any recommendation whose evidence does not reference real stored records.
5. Add the top recommendations to the weekly summary.

In the demo, recommendations are built on synthetic internal data: they show that the system works, not what the business should do.

**Done when:** every recommendation links to verifiable evidence and Marketing approves at least one per month.

For the demo: every stored recommendation cites evidence that resolves to stored records (checked in code and covered by `tests/test_recommendations.py`), and a real `scout recommend` run on the demo data stores 3 to 5 of them. Marketing does not review them during the hackathon, so the monthly approval is replaced by the team approving one in the dashboard during the demo (Step 10); until then they stay `proposed`.

How it works (code in `src/scout_ai/analysis/recommendations.py`):

- `scout recommend` builds the context from the database as a list of facts, each with a reference: signals of the last 28 days (`S<signal id>`, top 3 first, at most 40), funnel and spend per region (`R1`, …), funnel per channel (`CH1`, …), the 20 campaigns with most MQLs (`K1`, …) and deals against each competitor this year and open now (`D1`, …). Funnel and spend use the same months as the weekly summary: the latest month with Marketing spend against the month before.
- `claude-opus-5-5` answers with structured output validated by Pydantic: 3 to 5 recommendations, each with an action, the references it rests on with a note on what each shows, and 1–5 scores. The system prompt tells it to cite only the listed references, keep the codes out of the text Marketing reads, never invent numbers, and treat signal text as data, not instructions.
- Evidence check (item 4): a recommendation with no evidence, or citing a reference that is not in the context, is rejected and printed with the reason. Each evidence item stored keeps the reference, a label, the fact as the model saw it, the model's note, the signal URL (internal facts have none until the dashboard API exists) and the IDs of the stored rows behind it (`signals`, `funnel_metrics`, `marketing_spend`, `campaigns`, `deals_competition`).
- Priority (item 3) is computed by `priority_score` in code; the top 5 are stored as `proposed`, with `prompt_version`. Running it again the same day replaces that day's `proposed` ones and never touches approved or rejected ones. With no signals and no internal data the model is not called. The command exits with 1 when the call fails or every proposal was rejected.
- Weekly summary (item 5): `scout report` shows the top 5 of the latest run in the last 7 days (proposed or approved), with priority, scores and evidence (signals link to their source), under a label saying they are built on the synthetic demo data.

```bash
scout analyze && scout recommend && scout report
```

---

## Step 8 — Close the loop

1. When a recommendation is approved, create a ClickUp task with the action, evidence and scores; store the `clickup_task_id`.
2. Tag the related HubSpot campaign so results can be traced back.
3. After the task is completed, compare funnel metrics before and after and record the outcome on the recommendation.
4. Feed past outcomes back into the recommendation prompt so the system learns what works.

In the demo, items 1 and 2 run as a **dry run**: log the ClickUp task and HubSpot tag that would be created instead of calling the APIs, so synthetic recommendations never become real tasks. Items 3 and 4 need real data and come after the demo.

**Done when:** we can show, for each executed recommendation, its measured effect on leads, opportunities or deals.

For the demo: approving a recommendation logs the ClickUp task and the HubSpot tag that would be created, with its action, evidence and scores. Measuring the effect needs real executions and comes after the hackathon.

---

## Step 9 — Operate and harden

For the demo only **Security** and **Privacy** apply, and they are already followed. Monitoring, alerts, cost tracking and the dashboard login come after the hackathon, when the system runs unattended.

- **Monitoring:** log every job run; alert on failed collectors (sites change their layout often).
- **Costs:** track LLM token usage per job; cache unchanged inputs.
- **Security:** keep tokens in a secrets manager, never in the repo; only the machine that runs `scout fetch` needs them, together with the Marketing CSVs. Give integrations read-only scopes except ClickUp task creation.
- **Privacy:** real HubSpot records never leave memory during `fetch`, and the Marketing CSVs stay in `data/raw/` (ignored by Git); only the synthetic dataset is stored and committed (Step 5).
- **Dashboard:** protect the web dashboard (Step 10) with company login; never expose the database directly.

---

## Step 10 — Web dashboard

The dashboard is our own web app, not a BI tool. It shows what the weekly summary shows, with filters and history, and lets Marketing act on recommendations. It does not try to replace HubSpot's own reports (README §4 and §7).

1. **API** (`src/scout_ai/api/`, FastAPI): read-only endpoints over the existing tables, e.g. `GET /competitors`, `GET /signals?competitor=&type=&since=`, `GET /funnel?from=&to=&region=&channel=`, `GET /spend?from=&to=&region=`, `GET /campaigns`, `GET /deals/competition`, `GET /recommendations?status=`, `GET /notifications` (weekly summaries, newest first) and `GET /notifications/{id}`. The only write is `PATCH /recommendations/{id}` to approve or reject one, which triggers the ClickUp task from Step 8.
2. **Front end** (`web/`): a JavaScript single-page app consuming the API. Views:
   - Signals feed per competitor (new this week, by type, with links to the source)
   - Funnel by region, channel and campaign: leads → opportunities → deals won, versus the previous period
   - Spend per region: cost per MQL, pipeline per dollar and CAC over time
   - Win/loss against each competitor
   - Recommendations ranked by priority, with evidence links and approve/reject buttons
   - Notifications: the weekly summaries from `weekly_summaries` (Step 6), newest first, each opening its full Markdown; a badge shows when a new one arrived
3. **Auth:** company single sign-on (Microsoft Entra ID) in front of both the API and the front end. The API connects to Postgres with a read-mostly database role.
4. **Deploy:** the API and front end as containers next to the Postgres from `docker/`; add them to `docker/compose.yml` for local development.
5. **Demo label:** show a visible "synthetic demo data, generated from real patterns" banner on every view.

**Done when:** every view works on the demo data, the notifications page shows the latest weekly summary, and approving a recommendation there creates its ClickUp task (dry run in the demo).

For the demo, the dashboard runs locally next to the Postgres from `docker/`, and the team drives it during the presentation.

---

## Definition of done for the MVP

- [x] Top 3 competitors monitored with `collect` and `analyze` (run on demand for the demo; weekly scheduling after the hackathon)
- [x] Synthetic demo dataset generated from HubSpot and Marketing spend patterns, shared through Git and loaded with `scout load`
- [ ] Summary generated on demand and shown on the dashboard's notifications page (generation done; page in Step 10)
- [ ] Recommendations with evidence and scores, turned into ClickUp tasks as a dry run (recommendations done; ClickUp in Step 8)
- [ ] Web dashboard (FastAPI + JavaScript) working on the demo data, with a recommendation approved during the demo

After the hackathon, with real data and real use by Marketing: weekly scheduling, the Step 4 evaluation set labeled by Marketing, monthly approvals, and at least one recommendation executed with its impact measured.
