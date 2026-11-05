"""Signal extraction (guide Step 4) on SQLite, with a fake extractor instead of the LLM."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, delete, select
from sqlalchemy.orm import Session

from scout_ai import llm
from scout_ai.analysis.signals import (
    MAX_DIFF_CHARS,
    PROMPT_VERSION,
    ExtractedSignal,
    Extraction,
    Status,
    analyze_snapshots,
    build_diff,
    has_changes,
)
from scout_ai.collectors.base import content_hash
from scout_ai.db.models import (
    Competitor,
    CompetitorTier,
    Signal,
    SignalType,
    Snapshot,
    Source,
    SourceType,
)
from scout_ai.db.setup import setup_database

NEWS = "https://acme.test/news/"
OLD = "Acme adds a CAPA module | https://acme.test/news/capa"
NEW = "Acme opens an office in São Paulo | https://acme.test/news/sao-paulo"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    engine = create_engine(url)
    with Session(engine) as session, session.begin():
        session.execute(delete(Source))
        session.execute(delete(Competitor))
        acme = Competitor(name="Acme", website="https://acme.test/", tier=CompetitorTier.TOP3)
        acme.sources = [Source(type=SourceType.PRESS, url=NEWS)]
        session.add(acme)
    yield engine
    engine.dispose()


def _add_snapshots(engine: Engine, *texts: str) -> None:
    with Session(engine) as session, session.begin():
        source = session.scalars(select(Source)).one()
        for text in texts:
            session.add(
                Snapshot(source_id=source.id, content_hash=content_hash(text), raw_text=text)
            )


class FakeExtractor:
    def __init__(self, *answers: Extraction | Exception) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> Extraction:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _signal(url: str = "https://acme.test/news/sao-paulo") -> ExtractedSignal:
    return ExtractedSignal(
        type=SignalType.PRESS_RELEASE,
        title="Acme opens an office in São Paulo",
        summary="Acme announced a new office in São Paulo. It will serve Brazilian labs.",
        relevance="Direct presence in Brazil, myLIMS's home market.",
        url=url,
    )


def _analyze(engine: Engine, extractor: FakeExtractor) -> list[Status]:
    with Session(engine) as session:
        return [r.status for r in asyncio.run(analyze_snapshots(session, extractor))]


def _signals(engine: Engine) -> list[Signal]:
    with Session(engine) as session:
        return list(session.scalars(select(Signal).order_by(Signal.id)))


def test_build_diff_shows_only_changes_with_context() -> None:
    previous = "\n".join(f"line {i}" for i in range(10))
    current = previous.replace("line 5", "line five")
    diff = build_diff(previous, current)
    assert "-line 5" in diff and "+line five" in diff
    assert "line 0" not in diff  # outside the context window
    assert not diff.startswith(("---", "+++"))
    assert has_changes(diff)


def test_build_diff_is_capped() -> None:
    diff = build_diff("", "\n".join("x" * 100 for _ in range(1000)))
    assert len(diff) <= MAX_DIFF_CHARS + 20
    assert diff.endswith("[diff truncated]")


def test_first_snapshot_is_a_baseline_without_llm(engine: Engine) -> None:
    _add_snapshots(engine, OLD)
    extractor = FakeExtractor()
    assert _analyze(engine, extractor) == [Status.BASELINE]
    assert extractor.prompts == []
    assert _analyze(engine, extractor) == []  # never analyzed twice


def test_meaningful_change_creates_signals(engine: Engine) -> None:
    _add_snapshots(engine, OLD, f"{NEW}\n{OLD}")
    extractor = FakeExtractor(Extraction(meaningful_change=True, signals=[_signal()]))
    assert _analyze(engine, extractor) == [Status.BASELINE, Status.SIGNALS]

    prompt = extractor.prompts[0]
    assert "Competitor: Acme (top3 competitor)" in prompt
    assert f"Page: press {NEWS}" in prompt
    assert f"+{NEW}" in prompt and f" {OLD}" in prompt

    [signal] = _signals(engine)
    assert signal.type is SignalType.PRESS_RELEASE
    assert signal.url == "https://acme.test/news/sao-paulo"
    assert signal.prompt_version == PROMPT_VERSION
    assert signal.snapshot_id is not None
    with Session(engine) as session:
        versions = set(session.scalars(select(Snapshot.analysis_prompt_version)))
    assert versions == {PROMPT_VERSION}


def test_not_meaningful_change_is_discarded_but_marked(engine: Engine) -> None:
    _add_snapshots(engine, OLD, f"{OLD}\nCookie settings")
    # Signals returned with meaningful_change=false are ignored too.
    extractor = FakeExtractor(Extraction(meaningful_change=False, signals=[_signal()]))
    assert _analyze(engine, extractor) == [Status.BASELINE, Status.NO_CHANGE]
    assert _signals(engine) == []
    assert _analyze(engine, extractor) == []


def test_whitespace_only_change_skips_the_llm(engine: Engine) -> None:
    _add_snapshots(engine, OLD, f"{OLD}\n")
    extractor = FakeExtractor()
    assert _analyze(engine, extractor) == [Status.BASELINE, Status.NO_CHANGE]
    assert extractor.prompts == []


def test_invented_urls_fall_back_to_the_page(engine: Engine) -> None:
    _add_snapshots(engine, OLD, f"{NEW}\n{OLD}")
    extractor = FakeExtractor(
        Extraction(meaningful_change=True, signals=[_signal("https://acme.test/made-up")])
    )
    _analyze(engine, extractor)
    assert [signal.url for signal in _signals(engine)] == [NEWS]


@pytest.mark.parametrize(
    "error",
    [llm.LLMError("rate limited"), ValueError("not used")],
)
def test_failures_are_retried_on_the_next_run(engine: Engine, error: Exception) -> None:
    _add_snapshots(engine, OLD, f"{NEW}\n{OLD}")
    if isinstance(error, ValueError):
        # A reply that does not match the schema.
        try:
            Extraction.model_validate({"meaningful_change": "maybe", "signals": []})
        except Exception as validation_error:
            error = validation_error
    first = FakeExtractor(error)
    assert _analyze(engine, first) == [Status.BASELINE, Status.FAILED]

    second = FakeExtractor(Extraction(meaningful_change=True, signals=[_signal()]))
    assert _analyze(engine, second) == [Status.SIGNALS]
    assert len(_signals(engine)) == 1


def test_schema_rejects_unknown_types_and_fields() -> None:
    with pytest.raises(ValueError):
        Extraction.model_validate(
            {"meaningful_change": True, "signals": [{**_signal().model_dump(), "type": "rumor"}]}
        )
    with pytest.raises(ValueError):
        Extraction.model_validate({"meaningful_change": True, "signals": [], "extra": 1})
