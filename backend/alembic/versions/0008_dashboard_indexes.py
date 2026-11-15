"""dashboard performance indexes

Revision ID: 0008_dashboard_indexes
Revises: 0007_auth_hardening
Create Date: 2026-11-07 00:00:00.000000

Adds indexes to support efficient dashboard summary aggregation:

- idx_bids_closing_date: supports open/closed/closing_soon filters on bids
- idx_bid_scores_bid_id_created: supports latest-score-per-bid lookup

All indexes are reversible and preserve existing records.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_dashboard_indexes"
down_revision: Union[str, None] = "0007_auth_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_bids_closing_date", "bids", ["closing_date"])
    op.create_index(
        "idx_bid_scores_bid_id_created", "bid_scores", ["bid_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_bid_scores_bid_id_created", table_name="bid_scores")
    op.drop_index("idx_bids_closing_date", table_name="bids")
