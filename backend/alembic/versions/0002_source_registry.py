"""source registry

Adds the configurable multi-source registry tables: ``data_sources`` (one row
per configured source) and ``source_runs`` (per-attempt run history with
per-stage counters and safe error details). Credentials are never stored
directly; ``data_sources.config`` may only reference secrets by
environment-variable name.

Revision ID: 0002_source_registry
Revises: 0001_initial_schema
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0002_source_registry'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'data_sources',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('source_id', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('base_url', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('adapter_key', sa.String(100), nullable=False),
        sa.Column('enabled', sa.Boolean(), default=True, nullable=False),
        sa.Column('collection_interval_minutes', sa.Integer(), default=60, nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), default='IDLE', nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_discovered', sa.Integer(), default=0, nullable=False),
        sa.Column('last_validated', sa.Integer(), default=0, nullable=False),
        sa.Column('last_rejected', sa.Integer(), default=0, nullable=False),
        sa.Column('last_inserted', sa.Integer(), default=0, nullable=False),
        sa.Column('last_updated', sa.Integer(), default=0, nullable=False),
        sa.Column('last_duplicates', sa.Integer(), default=0, nullable=False),
        sa.Column('total_runs', sa.Integer(), default=0, nullable=False),
        sa.Column('total_inserted', sa.Integer(), default=0, nullable=False),
        sa.Column('total_updated', sa.Integer(), default=0, nullable=False),
        sa.Column('total_duplicates', sa.Integer(), default=0, nullable=False),
        sa.Column('total_rejected', sa.Integer(), default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'source_runs',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('source_id', sa.CHAR(36), sa.ForeignKey('data_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trigger', sa.String(20), default='manual', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), default='RUNNING', nullable=False),
        sa.Column('pages_visited', sa.Integer(), default=0, nullable=False),
        sa.Column('records_discovered', sa.Integer(), default=0, nullable=False),
        sa.Column('validated', sa.Integer(), default=0, nullable=False),
        sa.Column('rejected', sa.Integer(), default=0, nullable=False),
        sa.Column('inserted', sa.Integer(), default=0, nullable=False),
        sa.Column('updated', sa.Integer(), default=0, nullable=False),
        sa.Column('duplicates', sa.Integer(), default=0, nullable=False),
        sa.Column('errors', sa.JSON(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('source_runs')
    op.drop_table('data_sources')