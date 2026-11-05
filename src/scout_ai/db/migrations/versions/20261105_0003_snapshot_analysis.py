"""snapshot analysis

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05 15:15:29.565973

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("snapshots", sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "snapshots", sa.Column("analysis_prompt_version", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("snapshots", "analysis_prompt_version")
    op.drop_column("snapshots", "analyzed_at")
