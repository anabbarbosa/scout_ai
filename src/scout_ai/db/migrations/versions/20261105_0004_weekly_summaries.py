"""weekly summaries

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-05 16:46:16.876081

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("month", sa.Date(), nullable=True),
        sa.Column("signal_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_summaries")),
        sa.UniqueConstraint("report_date", name=op.f("uq_weekly_summaries_report_date")),
    )


def downgrade() -> None:
    op.drop_table("weekly_summaries")
