# Scout AI — Marketing Intelligence Hub

Vision, scope, monitored competitors and roadmap. For step-by-step development instructions, see [guide.md](guide.md).

> **Core question:** How can we improve our marketing positioning to generate more sales opportunities and grow myLIMS revenue?

> **Hackathon project.** Scout AI is built as a demo: internal data is synthetic (Step 5 of the guide), and success checks that need weeks of real use by Marketing are adapted to what the demo can show.

## Status

| Guide step | State |
|---|---|
| 1. Project setup | Done: CI runs `ruff`, `mypy` and `pytest` |
| 2. Data model | Done: migrations `0001` to `0004`, seed with competitors and sources |
| 3. Competitor collectors | Done: 35 sources; LabVantage blocked, reviews not collected |
| 4. Signal extraction | Done with `claude-sonnet-5-5`; the evaluation set waits for real diffs |
| 5. Synthetic demo dataset | Done: `data/demo/`, regenerated on 2026-11-05 |
| 6. Weekly summary | Done: stored for the dashboard's notifications page |
| 7–10. Recommendations, closed loop, hardening, dashboard | Not started |

## Running it

```bash
docker compose -f docker/compose.yml up -d    # PostgreSQL on localhost:5434
pip install -r requirements-dev.txt
scout db-setup    # create the database, migrate, seed competitors and sources
scout load        # load the synthetic demo dataset from data/demo/
scout collect     # fetch competitor pages; a snapshot only when the text changed
scout analyze     # turn changes into signals with Claude (log in with `claude login`)
scout report      # weekly summary: stored for the notifications page and written to data/reports/
```

`scripts/weekly.ps1` runs `collect`, `analyze` and `report` in order. `scout fetch` regenerates the demo dataset and only runs where the HubSpot token and the Marketing CSVs are. Details are in [guide.md](guide.md).

---

## 1. Vision

The differentiator is **not scraping competitors**. It is cross-referencing market intelligence with Confience's internal data to turn information into decisions.

The platform is an **intelligence layer on top of the tools we already use** (HubSpot, Marketing's cost exports, and ClickUp for the actions it recommends). It does not replace the CRM and is not another generic dashboard.

Three modules connected in a single flow:

| Module | Question it answers | Inputs |
|---|---|---|
| **Market monitoring** | What are competitors doing? | Websites, blogs, events, webinars, press releases, LinkedIn, comparison pages, reviews (G2/Capterra) |
| **Internal data integration** | What does our data reveal about performance and sales? | HubSpot (leads, deals, attribution, revenue, campaigns), Marketing cost exports (spend per region) |
| **AI recommendations** | What should we test or change next? | Output of the two modules above |

### Hypothesis to validate

> The company does not necessarily need more data. It needs to turn the data it already has into better, faster decisions.

---

## 2. The problem

1. **Outdated competitive intelligence.** One-off analyses age quickly. Without continuous monitoring, we miss positioning shifts, new events, campaigns and content opportunities.
2. **Marketing disconnected from sales.** One channel may generate many leads but few deals; another, fewer leads but more qualified opportunities. Analysis must follow the funnel all the way to the deal, not stop at engagement.
3. **Scattered data and manual decisions.** Information lives in different tools and spreadsheets. Someone has to gather it, interpret it and turn conclusions into tasks.

---

## 3. Monitored competitors

### 3.1 Who we chose and why

We evaluated Clinisys, LabWare, CloudLIMS, LabVantage and STARLIMS. The criteria were: overlap with myLIMS segments (food, agribusiness, environmental, industrial, pharma), active presence in Brazil/Latin America, and size of the commercial threat.

**Top 3 (full monitoring):**

| # | Competitor | Why it is a priority |
|---|---|---|
| 1 | **LabWare** | Global enterprise benchmark (founded 1987), strong in highly regulated environments (pharma, government, manufacturing). This is who we win or lose large accounts against. In Brazil it operates mainly through integrators. |
| 2 | **STARLIMS** | Promoted on 2026-11-05: it shows up in HubSpot deals. Confience already runs a "best alternative to STARLIMS" page, so it is an active campaign target. Sold by Abbott to Francisco Partners (deal announced in 2021). Strong in regulated clinical and pharma labs. |
| 3 | **Clinisys** | Back in the top 3 on 2026-11-05, replacing LabVantage. Consolidated Sunquest, Horizon Lab Systems and ApolloLIMS (2022). HORIZON LIMS covers environmental, water quality, public health and agriculture labs — direct overlap with myLIMS segments. Aggressive acquisition strategy. It does not appear in HubSpot deals yet: watch whether that changes. |

**Watchlist (light monitoring):**

| Competitor | Reason |
|---|---|
| **LabVantage** | Moved out of the top 3 on 2026-11-05 because it cannot be collected: labvantage.com and Business Wire (where it publishes press releases) answer 403 to bots, robots.txt included, and Google News disallows its RSS. Still a priority by business criteria (2nd after LabWare in deals in the demo dataset, which keeps the HubSpot proportions) and the most active competitor in our home market: acquired professional services firms in Brazil and Colombia (2023), names Brazil as a growth front (2024) and partners with LIDERSALES for the Brazilian market. Named "2024 Global LIMS Company of the Year" by Frost & Sullivan. Its homepage stays listed, so `scout collect` notices if the site lets bots in. |
| **CloudLIMS** | Low-cost SaaS, per-user pricing, focused on small labs (2–50 people). A threat in the entry-level segment, not in enterprise accounts. |

> ⚠️ **Validate with internal data before finalizing the list.** The prioritization above is based on public research. The definitive criterion should be: who we actually compete against in HubSpot (a "competitor" field on won/lost deals). If that field does not exist, creating it is the project's first task.

### 3.2 Positioning comparison

| Dimension | **myLIMS (Confience)** | **LabVantage** | **LabWare** | **Clinisys** |
|---|---|---|---|---|
| Origin | Labsoft, Jundiaí, Brazil (2002); acquired by Confience (STG group) in June 2025 | USA, ~40 years in the market | USA, 1987 | UK/USA; consolidation of Sunquest + Horizon + Apollo |
| Model | Cloud LIMS | Integrated platform (LIMS + ELN + data), cloud-oriented | Enterprise, highly configurable | Laboratory platform (LIS + LIMS) |
| Strong segments | Food, agribusiness, environmental, industrial, LatAm | Life sciences, pharma | Pharma, government, regulated manufacturing | Clinical/diagnostics, environmental, public health, agriculture |
| Brazil presence | Strong, local team | Growing (local acquisitions, partner) | Through integrators | To be confirmed |
| Core message | Usability, LatAm leadership, global ambition | Integrated, award-winning platform | Functional depth and compliance | Scale and portfolio breadth |
| Exploitable weakness | Confience brand still new after the acquisition | Lower G2 rating (3.8/5, few reviews) | Complex, costly implementation | Integrating many acquired products |

### 3.3 Signals to monitor per competitor

- Messaging changes on the homepage and product/segment pages
- New comparison pages ("alternative to", "vs")
- Events, trade shows and webinars (especially in Brazil/LatAm)
- Published content (blog, whitepapers, case studies) and recurring themes
- Press releases: acquisitions, partnerships, new customers, awards
- Job openings (signal regional expansion and product investment)
- G2/Capterra reviews: recurring praise and complaints (not collected: Capterra's `robots.txt` disallows bots and G2's terms forbid automated access; it would need a paid data agreement or a manual export)
- Public pricing and offers (especially relevant for CloudLIMS)

---

## 4. Existing market and where we innovate

| Category | Examples | Role in the project |
|---|---|---|
| Market intelligence | Semrush, Similarweb | Reference and possible source for benchmarking digital presence, traffic and search |
| Performance and attribution | HubSpot Marketing Analytics | We already have it. We will **complement** it, not reproduce its dashboards |
| CRM-integrated CI | ConnectCurator | Shows that bringing competitor signals into HubSpot is already being explored |

**Our differentiator:** not competing on feature count. Building a **decision layer** tailored to Confience's reality that connects, in a single flow:

1. What competitors are doing.
2. What internal data reveals about performance and sales.
3. What the company should test or change next.

---

## 5. Recommendations: how to prioritize

Every AI-generated recommendation must include:

- A concrete **action** (e.g., "create a myLIMS vs LabVantage comparison page for pharma")
- The **evidence** behind it, linked to its source (external signal + internal metric)
- A **score** on four axes (1–5):

| Axis | Question |
|---|---|
| Commercial impact | How much could it affect opportunities and revenue? |
| Cost | How much does it cost to execute? |
| Effort | How much time/team does it require? |
| Evidence confidence | How solid is the data supporting the recommendation? |

Suggested priority: `impact × confidence ÷ (cost + effort)`. Approved recommendations become ClickUp tasks, and results flow back into HubSpot, closing the loop.

---

## 6. Suggested roadmap

| Phase | Deliverable | Success criterion |
|---|---|---|
| **0 — Discovery** | Map available data in HubSpot and the Marketing cost exports; confirm competitors from deals | Competitor list validated by data; API access in place |
| **1 — Monitoring** | Periodic collection of signals for the top 3 competitors + weekly summary | Weekly summary generated from collected signals and shown on the dashboard's notifications page |
| **2 — Integration** | Connect HubSpot and Marketing spend: leads → opportunities → deals and cost by region, channel and campaign | Reliable view of which channels generate deals, not just leads |
| **3 — Recommendations** | AI cross-references external and internal signals and produces scored actions | At least one recommendation executed and measured per month |
| **4 — Closed loop** | Recommendations → ClickUp → results measured in HubSpot | Measure the pipeline impact of suggested actions |

> **Demo data.** The first version is a demo presented to a wide audience, so internal data is **synthetic**: generated from the patterns of the real HubSpot data and Marketing spend, with no real company, person, campaign or amount. ClickUp tasks are shown as a dry run. See [guide.md](guide.md) Step 5.

---

## 7. Risks and caveats

- **CRM data quality:** attribution is only useful if source, campaign and competitor fields are filled in consistently. Example already found: deal amounts left at `0`, or typed as `0.01` to pass a required field, in 69 of 357 deals; `scout fetch` reads them as unknown.
- **Sites that block bots:** some competitors (LabVantage today) refuse automated access. We never work around a block; such a competitor is reported as `blocked` and cannot be in the top 3 while it lasts.
- **Public data collection:** respect terms of use and `robots.txt`; prefer APIs and official sources.
- **Third-party sources:** rankings from vendor content sites and consultancies are opinion, not fact. Always record the source.
- **Scope:** resist the temptation to become a BI tool or a CRM. The product is the recommendation.

---

## Sources

- [Confience — Bem Brasil customer story](https://www.confience.io/customer-story/bem-brasil)
- [Confience — Best alternative to STARLIMS](https://get.confience.io/best-alternative-to-starlims)
- [CB Insights — Labsoft Tecnologia](https://www.cbinsights.com/company/labsoft-tecnologia)
- [IntuitionLabs — LIMS Software Comparison 2026: LabWare vs STARLIMS](https://intuitionlabs.ai/articles/lims-software-comparison-2026)
- [IntuitionLabs — Commercial LIMS Comparison 2026](https://intuitionlabs.ai/articles/commercial-lims-comparison-2026)
- [G2 — LabWare vs Sapio vs STARLIMS](https://www.g2.com/compare/labware-lims-vs-sapio-lims-vs-starlims)
- [Digital Health — Clinisys completes acquisition of Sunquest, Horizon and Apollo](https://www.digitalhealth.net/2022/10/clinisys-completes-acquisition-of-sunquest-horizon-and-apollo/)
- [Digital Health — CliniSys acquires Horizon](https://www.digitalhealth.net/2022/01/clinsys-acquires-horizon/)
- [LIMSwiki — CliniSys, Inc.](https://test.limswiki.org/index.php/CliniSys,_Inc.)
- [Francisco Partners — to acquire STARLIMS](https://www.franciscopartners.com/news/francisco-partners-to-acquire-starlims)
- [LIMSwiki — STARLIMS Corporation](https://limswiki.org/index.php/Vendor:Starlims)
- [Capterra — CloudLIMS](https://www.capterra.co.uk/software/131317/cloudlims)
- [Business Wire — LabVantage (2023, Portuguese)](https://www.businesswire.com/news/home/20231019620105/pt)
- [Business Wire — LabVantage (2024, Portuguese)](https://www.businesswire.com/news/home/20240912910294/pt)
- [Estado de Minas — LabVantage named Global LIMS Company of the Year (Portuguese)](https://www.em.com.br/mundo-corporativo/2024/09/6940756-labvantage-e-nomeada-empresa-global-de-lims-do-ano-pela-frost-amp-sullivan.html)
