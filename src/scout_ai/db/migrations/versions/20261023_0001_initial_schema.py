"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-23 15:12:31.943886

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "top3",
                "watchlist",
                name="competitortier",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_competitors")),
        sa.UniqueConstraint("name", name=op.f("uq_competitors_name")),
    )
    op.create_table(
        "funnel_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=100), nullable=False),
        sa.Column("campaign", sa.String(length=200), server_default="", nullable=False),
        sa.Column("leads", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mqls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sqls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("opportunities", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deals_won", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revenue", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_funnel_metrics")),
        sa.UniqueConstraint(
            "period", "channel", "campaign", name=op.f("uq_funnel_metrics_period_channel_campaign")
        ),
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("impact", sa.SmallInteger(), nullable=False),
        sa.Column("cost", sa.SmallInteger(), nullable=False),
        sa.Column("effort", sa.SmallInteger(), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), nullable=False),
        sa.Column("priority", sa.Double(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "approved",
                "rejected",
                "in_progress",
                "done",
                name="recommendationstatus",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("clickup_task_id", sa.String(length=50), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 1 AND 5", name=op.f("ck_recommendations_confidence_range")
        ),
        sa.CheckConstraint("cost BETWEEN 1 AND 5", name=op.f("ck_recommendations_cost_range")),
        sa.CheckConstraint("effort BETWEEN 1 AND 5", name=op.f("ck_recommendations_effort_range")),
        sa.CheckConstraint("impact BETWEEN 1 AND 5", name=op.f("ck_recommendations_impact_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
    )
    with op.batch_alter_table("recommendations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_recommendations_priority"), ["priority"], unique=False)
        batch_op.create_index(batch_op.f("ix_recommendations_status"), ["status"], unique=False)

    op.create_table(
        "deals_competition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.String(length=50), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "open",
                "won",
                "lost",
                name="dealoutcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["competitor_id"],
            ["competitors.id"],
            name=op.f("fk_deals_competition_competitor_id_competitors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals_competition")),
        sa.UniqueConstraint(
            "deal_id", "competitor_id", name=op.f("uq_deals_competition_deal_id_competitor_id")
        ),
    )
    with op.batch_alter_table("deals_competition", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_deals_competition_competitor_id"), ["competitor_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_deals_competition_deal_id"), ["deal_id"], unique=False)

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "homepage",
                "segment_page",
                "comparison",
                "blog",
                "events",
                "press",
                "jobs",
                "reviews",
                "pricing",
                name="sourcetype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "daily",
                "weekly",
                "monthly",
                name="frequency",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["competitor_id"],
            ["competitors.id"],
            name=op.f("fk_sources_competitor_id_competitors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("competitor_id", "url", name=op.f("uq_sources_competitor_id_url")),
    )
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sources_competitor_id"), ["competitor_id"], unique=False
        )

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_snapshots_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.create_index(
            "ix_snapshots_source_id_fetched_at", ["source_id", "fetched_at"], unique=False
        )

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "messaging_change",
                "comparison_page",
                "event",
                "content",
                "press_release",
                "job_posting",
                "review",
                "pricing",
                "other",
                name="signaltype",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["competitor_id"],
            ["competitors.id"],
            name=op.f("fk_signals_competitor_id_competitors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_signals_snapshot_id_snapshots"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_signals_competitor_id"), ["competitor_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_signals_snapshot_id"), ["snapshot_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("signals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_signals_snapshot_id"))
        batch_op.drop_index(batch_op.f("ix_signals_competitor_id"))

    op.drop_table("signals")
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.drop_index("ix_snapshots_source_id_fetched_at")

    op.drop_table("snapshots")
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sources_competitor_id"))

    op.drop_table("sources")
    with op.batch_alter_table("deals_competition", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_deals_competition_deal_id"))
        batch_op.drop_index(batch_op.f("ix_deals_competition_competitor_id"))

    op.drop_table("deals_competition")
    with op.batch_alter_table("recommendations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_recommendations_status"))
        batch_op.drop_index(batch_op.f("ix_recommendations_priority"))

    op.drop_table("recommendations")
    op.drop_table("funnel_metrics")
    op.drop_table("competitors")
