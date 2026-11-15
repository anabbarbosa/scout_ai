"""A static copy of the web dashboard for GitHub Pages (`scout pages`).

GitHub Pages serves files only, so the dashboard's answers are taken once from the API
(read-only GETs through FastAPI's test client) and written to `snapshot.json` next to a copy
of the front end; `web/snapshot.js` answers the page's API calls from that file. Approving a
play needs the server, so each proposed recommendation is approved inside a transaction that
is rolled back, and the dry-run answer is stored for the page to show.

Everything in the snapshot is what the dashboard already shows: the synthetic demo data and
the competitor signals collected from public websites.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from scout_ai.api import WEB_DIR, _recommendation, create_app
from scout_ai.review import approve

FUNNEL_GROUPS = ("region", "channel", "campaign", "total")


def build_snapshot(engine: Engine) -> dict[str, Any]:
    client = TestClient(create_app(engine))

    def get(path: str) -> Any:
        response = client.get(f"/api{path}")
        response.raise_for_status()
        return response.json()

    deals = get("/deals/competition")
    recommendations = get("/recommendations")
    return {
        "built_at": datetime.now(UTC).isoformat(),
        "meta": get("/meta"),
        "competitors": get("/competitors"),
        "signals": get("/signals?limit=500"),
        "funnel": {by: get(f"/funnel?by={by}") for by in FUNNEL_GROUPS},
        "spend": get("/spend"),
        "deals": {"default": deals}
        | {str(year): get(f"/deals/competition?year={year}") for year in deals["years"]},
        "recommendations": recommendations,
        "notifications": [get(f"/notifications/{n['id']}") for n in get("/notifications")],
        "approvals": {
            str(rec["id"]): dry_run_approval(engine, rec["id"])
            for rec in recommendations
            if rec["status"] == "proposed"
        },
    }


def dry_run_approval(engine: Engine, recommendation_id: int) -> dict[str, Any]:
    """What `PATCH /api/recommendations/{id}` would answer on approval, without saving it."""
    with Session(engine) as session:
        result = approve(session, recommendation_id)
        answer = {
            "recommendation": _recommendation(result.recommendation),
            "dry_run": result.dry_run,
            "clickup_task": result.task.body() if result.task else None,
            "hubspot_tags": [{"campaign": t.campaign, "tag": t.tag} for t in result.tags],
        }
        session.rollback()
    return answer


def build_site(engine: Engine, out: Path) -> Path:
    """Write the static site to `out`, replacing what was there."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB_DIR, out / "static", ignore=shutil.ignore_patterns("index.html"))
    page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    page = page.replace('"/static/', '"static/').replace(
        '<html lang="en">', '<html lang="en" data-snapshot="snapshot.json">', 1
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    snapshot = json.dumps(build_snapshot(engine), ensure_ascii=False, separators=(",", ":"))
    (out / "snapshot.json").write_text(snapshot, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return out
