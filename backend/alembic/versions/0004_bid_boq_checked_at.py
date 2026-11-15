"""bid boq checked-at marker

Adds ``bids.boq_checked_at``: the timestamp of the last *attempt* at automatic
BoQ enrichment (see ``app/services/ingestion/gem_boq_auto.py``). It lets a bid
that publishes no BoQ line-item CSV be skipped on later collection runs, so
automatic enrichment never re-fetches the same bid.

Nullable and additive: existing rows keep ``NULL`` (never attempted) and no
existing behaviour changes.

Revision ID: 0004_bid_boq_checked_at
Revises: 0003_bid_boq_items
Create Date: 2026-10-13 21:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0004_bid_boq_checked_at'
down_revision: Union[str, None] = '0003_bid_boq_items'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bids', sa.Column('boq_checked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('bids', 'boq_checked_at')
