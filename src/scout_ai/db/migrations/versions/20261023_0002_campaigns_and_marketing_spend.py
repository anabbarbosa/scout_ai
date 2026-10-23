"""campaigns and marketing spend

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 17:26:57.326850

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("first_mql_at", sa.Date(), nullable=True),
        sa.Column("last_mql_at", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaigns")),
        sa.UniqueConstraint("name", name=op.f("uq_campaigns_name")),
    )
    op.create_table(
        "marketing_spend",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column(
            "region",
            sa.Enum(
                "north_america",
                "brazil",
                "latam",
                "emea",
                "apac",
                "other",
                name="region",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketing_spend")),
        sa.UniqueConstraint("period", "region", name=op.f("uq_marketing_spend_period_region")),
    )
    with op.batch_alter_table("funnel_metrics", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "region",
                sa.Enum(
                    "north_america",
                    "brazil",
                    "latam",
                    "emea",
                    "apac",
                    "other",
                    name="region",
                    native_enum=False,
                    create_constraint=True,
                    length=32,
                ),
                nullable=False,
            )
        )
        batch_op.drop_constraint(
            batch_op.f("uq_funnel_metrics_period_channel_campaign"), type_="unique"
        )
        batch_op.create_unique_constraint(
            batch_op.f("uq_funnel_metrics_period_region_channel_campaign"),
            ["period", "region", "channel", "campaign"],
        )


def downgrade() -> None:
    with op.batch_alter_table("funnel_metrics", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("uq_funnel_metrics_period_region_channel_campaign"), type_="unique"
        )
        batch_op.create_unique_constraint(
            batch_op.f("uq_funnel_metrics_period_channel_campaign"),
            ["period", "channel", "campaign"],
        )
        # The Enum CHECK on region must go first, or SQLite's table rebuild still references it.
        batch_op.drop_constraint(batch_op.f("ck_funnel_metrics_region"), type_="check")
        batch_op.drop_column("region")

    op.drop_table("marketing_spend")
    op.drop_table("campaigns")
