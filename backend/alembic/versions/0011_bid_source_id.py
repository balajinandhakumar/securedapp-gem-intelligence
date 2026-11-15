"""Add source_id foreign key to bids

Adds a ``source_id`` column to the ``bids`` table linking each bid to the
``data_sources`` row that collected it. This is the authoritative state
attribution: the state-wise views join ``Bid.source_id == DataSource.id``
instead of the fragile ``Bid.source_name == DataSource.name`` string join,
which splits states whose portal display name has variants
(e.g. ``Jammu & Kashmir e-Procurement`` vs ``Jammu and Kashmir e-Procurement``).

The column is nullable (``ondelete="SET NULL"``): historical bids whose source
row is removed keep their ``source_name`` text but lose the registry link.
Existing rows are backfilled by matching ``Bid.source_name`` to
``DataSource.name``, with an explicit variant map for the known name variants.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models.base_mixins import GUID

revision: str = '0011_bid_source_id'
down_revision: Union[str, None] = '0010_bid_original_bid_url'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("bids") as batch_op:
        batch_op.add_column(
            sa.Column("source_id", GUID(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("bids") as batch_op:
        batch_op.drop_constraint("fk_bids_source_id_data_sources", type_="foreignkey")
        batch_op.drop_column("source_id")
