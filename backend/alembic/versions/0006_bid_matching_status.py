"""Add matching status tracking to bids

Adds ``matching_status`` (PENDING/PROCESSING/COMPLETED/FAILED) and
``matched_at`` timestamp columns to the ``bids`` table to support batch
state-wise tender product matching with retry support.

Additive only: no existing tables or columns are modified, and no existing
data is touched. Safe to apply to a database with historical records.

Revision ID: 0006_bid_matching_status
Revises: 0005_source_discovery_ledger
Create Date: 2026-11-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006_bid_matching_status'
down_revision: Union[str, None] = '0005_source_discovery_ledger'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check whether a column exists (works on SQLite and PostgreSQL)."""
    if conn.dialect.name == 'sqlite':
        result = conn.execute(
            sa.text(
                "SELECT 1 FROM pragma_table_info(:table) WHERE name=:column"
            ),
            {"table": table_name, "column": column_name},
        ).fetchone()
    else:
        result = conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=:table AND column_name=:column"
            ),
            {"table": table_name, "column": column_name},
        ).fetchone()
    return result is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, 'bids', 'matching_status'):
        op.add_column(
            'bids',
            sa.Column(
                'matching_status',
                sa.String(50),
                nullable=False,
                server_default='PENDING',
            ),
        )
        op.create_index(
            'ix_bids_matching_status', 'bids', ['matching_status']
        )

    if not _column_exists(conn, 'bids', 'matched_at'):
        op.add_column(
            'bids',
            sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _column_exists(conn, 'bids', 'matching_status'):
        op.drop_index('ix_bids_matching_status', table_name='bids')
        op.drop_column('bids', 'matching_status')

    if _column_exists(conn, 'bids', 'matched_at'):
        op.drop_column('bids', 'matched_at')
