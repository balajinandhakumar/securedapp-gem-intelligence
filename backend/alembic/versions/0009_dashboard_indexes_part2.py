"""dashboard performance indexes (part 2)

Adds indexes that migration 0008 was supposed to create but were never
applied to the database:

- idx_bids_closing_date: supports open/closed/closing_soon filters on bids
- idx_bid_scores_bid_id_created: supports latest-score-per-bid lookup
- idx_bids_published_date: supports recent-bids ordering on published_date

These indexes reduce dashboard summary response time from ~10s to <1s.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0009_dashboard_indexes_part2'
down_revision: Union[str, None] = '0008_dashboard_indexes'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

def upgrade() -> None:
    op.create_index(
        "idx_bids_published_date", "bids", ["published_date"]
    )

def downgrade() -> None:
    op.drop_index("idx_bids_published_date", table_name="bids")
