"""bid boq line items

Adds ``bids.boq_items``: the authoritative Bill-of-Quantities line items for a
bid, fetched from the GeM BoQ CSV document linked from the bid PDF. GeM's
public listing truncates the item list to ~99 characters in its
``data-content`` popover, so ``title`` / ``scope_of_work`` only ever hold a
prefix of the real scope. The full line items are stored here, separately from
the title and scope of work, together with the exact source URL and the
retrieval timestamp.

Nullable and additive: existing rows keep ``NULL`` and the matching engine's
behaviour for them is unchanged.

Revision ID: 0003_bid_boq_items
Revises: 0002_source_registry
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0003_bid_boq_items'
down_revision: Union[str, None] = '0002_source_registry'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bids', sa.Column('boq_items', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('bids', 'boq_items')
