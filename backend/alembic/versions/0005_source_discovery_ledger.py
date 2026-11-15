"""source discovery ledger

Adds ``source_discoveries``: a ledger that records every GeM bid identifier
observed during collection, regardless of whether it was classified as
relevant enough to persist as a business bid.

This lets the system distinguish a bid that was genuinely never seen on GeM
from a bid that was discovered but classified NO_MATCH and therefore not
stored as a business bid.

Additive only: no existing tables or columns are modified, and no existing
data is touched. Safe to apply to a database with historical records.

Revision ID: 0005_source_discovery_ledger
Revises: 0004_bid_boq_checked_at
Create Date: 2026-11-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005_source_discovery_ledger'
down_revision: Union[str, None] = '0004_bid_boq_checked_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    """Check whether a table exists (works on SQLite and PostgreSQL)."""
    if conn.dialect.name == 'sqlite':
        result = conn.execute(
            sa.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
            ),
            {"name": table_name},
        ).fetchone()
    else:
        result = conn.execute(
            sa.text(
                "SELECT to_regclass(:name)"
            ),
            {"name": table_name},
        ).fetchone()
    return result is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, 'source_discoveries'):
        return  # Table already exists (e.g. created by metadata.create_all)

    op.create_table(
        'source_discoveries',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('gem_bid_id', sa.String(100), nullable=True),
        sa.Column('bid_number', sa.String(100), nullable=True),
        sa.Column('composite_identity', sa.String(64), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('listing_page', sa.Integer(), nullable=True),
        sa.Column(
            'collection_run_id',
            sa.CHAR(36),
            sa.ForeignKey('collection_runs.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'first_discovered_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'last_observed_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column('discovery_status', sa.String(20), nullable=False, server_default='discovered'),
        sa.Column('persisted_as_business_bid', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('relevance_score', sa.Float(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('organisation', sa.String(255), nullable=True),
        sa.Column('category', sa.String(255), nullable=True),
    )
    op.create_index(
        'ix_source_discoveries_gem_bid_id', 'source_discoveries', ['gem_bid_id']
    )
    op.create_index(
        'ix_source_discoveries_composite', 'source_discoveries', ['composite_identity']
    )
    op.create_index(
        'ix_source_discoveries_last_observed', 'source_discoveries', ['last_observed_at']
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, 'source_discoveries'):
        return

    op.drop_index('ix_source_discoveries_last_observed', table_name='source_discoveries')
    op.drop_index('ix_source_discoveries_composite', table_name='source_discoveries')
    op.drop_index('ix_source_discoveries_gem_bid_id', table_name='source_discoveries')
    op.drop_table('source_discoveries')
