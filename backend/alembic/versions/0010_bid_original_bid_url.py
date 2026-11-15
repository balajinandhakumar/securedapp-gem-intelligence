"""Add original_bid_url to bids

Adds a dedicated ``original_bid_url`` column to the ``bids`` table holding the
canonical URL of the original bid on the source portal (e.g. the GeM full-view
page or the bid document page). It is populated from ``source_url`` where that
URL is a public http(s) URL, and is used by the "View Original Bid" and
"Download Bid PDF" actions.

The column is nullable: bids whose source URL was never recorded, or was not a
web URL, keep a NULL value and clients fall back to ``source_url``.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010_bid_original_bid_url'
down_revision: Union[str, None] = '0009_dashboard_indexes_part2'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "bids",
        sa.Column("original_bid_url", sa.Text(), nullable=True),
    )
    # Backfill from source_url where it is a public http(s) URL. This is derived
    # data (a copy of an already-persisted portal URL), never fabricated, and
    # only ever references the bid's own recorded source.
    op.execute(
        """
        UPDATE bids
        SET original_bid_url = source_url
        WHERE original_bid_url IS NULL
          AND source_url IS NOT NULL
          AND (source_url LIKE 'http://%' OR source_url LIKE 'https://%')
        """
    )


def downgrade() -> None:
    op.drop_column("bids", "original_bid_url")
