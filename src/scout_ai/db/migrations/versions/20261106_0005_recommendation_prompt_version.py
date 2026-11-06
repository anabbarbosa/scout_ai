"""recommendation prompt version

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("prompt_version", sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recommendations", schema=None) as batch_op:
        batch_op.drop_column("prompt_version")
