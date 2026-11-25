"""add no_rankable_candidates recommendation status

Revision ID: 4b1f7c9d2e30
Revises: 8ffb5ef8915f
Create Date: 2026-11-25 00:00:00.000000

D-033 Option A: a completed recommendation whose evaluated carriers are all
ineligible (or insufficient_data) reports ``no_eligible_carriers``; a completed
recommendation with eligible carriers but zero rankable carriers reports
``no_rankable_candidates``. Neither uses ``ready`` or ``failed`` incorrectly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b1f7c9d2e30"
down_revision: Union[str, None] = "8ffb5ef8915f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = "'pending', 'computing', 'ready', 'no_eligible_carriers', 'failed', 'superseded'"
NEW_STATUSES = (
    "'pending', 'computing', 'ready', 'no_eligible_carriers', "
    "'no_rankable_candidates', 'failed', 'superseded'"
)


def upgrade() -> None:
    op.drop_constraint("chk_recommendations_status", "recommendations", type_="check")
    op.create_check_constraint(
        "chk_recommendations_status",
        "recommendations",
        f"status IN ({NEW_STATUSES})",
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(
        sa.text(
            "SELECT count(*) FROM recommendations "
            "WHERE status = 'no_rankable_candidates'"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade: recommendations with status 'no_rankable_candidates' "
            "exist. No lossless mapping to a pre-D-033 status is defined; preserve "
            "the rows and contract version instead of rewriting audited outcomes."
        )
    op.drop_constraint("chk_recommendations_status", "recommendations", type_="check")
    op.create_check_constraint(
        "chk_recommendations_status",
        "recommendations",
        f"status IN ({OLD_STATUSES})",
    )
