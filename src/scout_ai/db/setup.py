"""Create the database, apply migrations and seed it: `scout db-setup`."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from scout_ai.db.seed import seed

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def create_database(url: str | URL) -> bool:
    """Create the PostgreSQL database named in `url` if missing. Returns True if created.

    SQLite needs nothing here: the file is created on first connection.
    """
    url = make_url(url)
    if url.get_backend_name() != "postgresql":
        return False
    if not url.database:
        raise ValueError("DATABASE_URL must name a database, e.g. .../scout_ai")

    # CREATE DATABASE cannot run inside a transaction, and needs a connection to another db.
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if exists:
                return False
            quoted = conn.dialect.identifier_preparer.quote(url.database)
            conn.execute(text(f"CREATE DATABASE {quoted} ENCODING 'UTF8' TEMPLATE template0"))
            return True
    finally:
        admin.dispose()


def alembic_config(url: str | URL) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser treats % as interpolation, so escape it (URL-encoded passwords).
    url_str = make_url(url).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url_str.replace("%", "%%"))
    return config


def migrate(url: str | URL, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def setup_database(url: str | URL) -> None:
    created = create_database(url)
    print(f"database: {'created' if created else 'already exists'}")
    migrate(url)
    print("migrations: up to date")

    engine = create_engine(url)
    try:
        with Session(engine) as session, session.begin():
            seed(session)
    finally:
        engine.dispose()
    print("seed: competitors and sources in place")
