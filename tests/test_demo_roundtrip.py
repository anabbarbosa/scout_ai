"""guide Step 5 "Done when": the files `scout fetch` writes load into the same tables anywhere."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from scout_ai.db.setup import setup_database
from scout_ai.demo.load import MODELS, load_dataset
from scout_ai.demo.synthesize import synthesize, write_dataset
from tests.test_demo_synthesize import _deals, _mqls, _spend


def _engine(path: Path) -> Engine:
    url = f"sqlite:///{path.as_posix()}"
    setup_database(url)
    return create_engine(url)


def _counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            table: session.scalar(select(func.count()).select_from(model)) or 0
            for table, model in MODELS.items()
        }


def test_written_dataset_loads_the_same_tables_on_two_machines(tmp_path: Path) -> None:
    tables = synthesize(_deals(), _spend(), _mqls(), seed=42)
    manifest = write_dataset(tables, tmp_path / "demo", seed=42)

    engines = [_engine(tmp_path / "a.db"), _engine(tmp_path / "b.db")]
    for engine in engines:
        with Session(engine) as session:
            assert load_dataset(tmp_path / "demo", session) == manifest.row_counts

    counts = [_counts(engine) for engine in engines]
    assert counts[0] == counts[1] == manifest.row_counts
    for engine in engines:
        engine.dispose()
