"""initial schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('email', sa.String(255), unique=True, index=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), default='reviewer', nullable=False),
        sa.Column('active', sa.Boolean(), default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Products table
    op.create_table(
        'products',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('name', sa.String(100), unique=True, index=True, nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), default=True, nullable=False),
        sa.Column('priority', sa.Integer(), default=0, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Product capabilities table
    op.create_table(
        'product_capabilities',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('product_id', sa.CHAR(36), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('weight', sa.Float(), default=1.0, nullable=False),
        sa.Column('active', sa.Boolean(), default=True, nullable=False),
    )

    # Product keywords table
    op.create_table(
        'product_keywords',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('product_id', sa.CHAR(36), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('keyword', sa.String(255), index=True, nullable=False),
        sa.Column('weight', sa.Float(), default=1.0, nullable=False),
        sa.Column('type', sa.String(50), default='keyword', nullable=False),
        sa.Column('active', sa.Boolean(), default=True, nullable=False),
    )

    # Product technologies table
    op.create_table(
        'product_technologies',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('product_id', sa.CHAR(36), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('technology', sa.String(100), nullable=False),
    )

    # Product categories table
    op.create_table(
        'product_categories',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('product_id', sa.CHAR(36), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(255), nullable=False),
    )

    # Collection runs table
    op.create_table(
        'collection_runs',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('source_adapter', sa.String(100), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), default='RUNNING', nullable=False),
        sa.Column('records_found', sa.Integer(), default=0, nullable=False),
        sa.Column('records_new', sa.Integer(), default=0, nullable=False),
        sa.Column('records_duplicate', sa.Integer(), default=0, nullable=False),
        sa.Column('error_count', sa.Integer(), default=0, nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    # Raw bid payloads table
    op.create_table(
        'raw_bid_payloads',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('collection_run_id', sa.CHAR(36), sa.ForeignKey('collection_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('raw_content', sa.JSON(), nullable=False),
        sa.Column('source_reference', sa.String(255), nullable=True),
        sa.Column('checksum', sa.String(64), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Bids table
    op.create_table(
        'bids',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('gem_bid_id', sa.String(100), index=True, nullable=True),
        sa.Column('bid_number', sa.String(100), index=True, nullable=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('organisation', sa.String(255), nullable=True),
        sa.Column('department', sa.String(255), nullable=True),
        sa.Column('ministry', sa.String(255), nullable=True),
        sa.Column('category', sa.String(255), nullable=True),
        sa.Column('bid_type', sa.String(100), nullable=True),
        sa.Column('published_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('location', sa.String(255), nullable=True),
        sa.Column('estimated_value', sa.Numeric(15, 2), nullable=True),
        sa.Column('currency', sa.String(10), default='INR', nullable=False),
        sa.Column('scope_of_work', sa.Text(), nullable=True),
        sa.Column('technical_requirements', sa.JSON(), nullable=True),
        sa.Column('eligibility_criteria', sa.JSON(), nullable=True),
        sa.Column('qualification_requirements', sa.JSON(), nullable=True),
        sa.Column('experience_requirements', sa.JSON(), nullable=True),
        sa.Column('certification_requirements', sa.JSON(), nullable=True),
        sa.Column('emd_information', sa.JSON(), nullable=True),
        sa.Column('tender_fee_information', sa.JSON(), nullable=True),
        sa.Column('contact_information', sa.JSON(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('source_name', sa.String(255), nullable=True),
        sa.Column('search_text', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(64), index=True, nullable=True),
        sa.Column('status', sa.String(50), default='NEW', nullable=False),
        sa.Column('first_discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Bid status history table
    op.create_table(
        'bid_status_history',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('old_status', sa.String(50), nullable=True),
        sa.Column('new_status', sa.String(50), nullable=False),
        sa.Column('changed_by', sa.String(255), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Bid analysis table
    op.create_table(
        'bid_analysis',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('engine_version', sa.String(50), nullable=False),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('keyword_results', sa.JSON(), nullable=True),
        sa.Column('semantic_results', sa.JSON(), nullable=True),
        sa.Column('product_matches', sa.JSON(), nullable=True),
        sa.Column('eligibility_analysis', sa.JSON(), nullable=True),
        sa.Column('concerns', sa.JSON(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('llm_output', sa.JSON(), nullable=True),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Bid scores table
    op.create_table(
        'bid_scores',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('analysis_id', sa.CHAR(36), sa.ForeignKey('bid_analysis.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relevance_score', sa.Float(), nullable=False),
        sa.Column('opportunity_score', sa.Float(), nullable=False),
        sa.Column('relevance_label', sa.String(50), nullable=False),
        sa.Column('urgency', sa.String(50), nullable=False),
        sa.Column('score_breakdown', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Bid product matches table
    op.create_table(
        'bid_product_matches',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.CHAR(36), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('match_score', sa.Float(), nullable=False),
        sa.Column('match_type', sa.String(50), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), default=1.0, nullable=False),
    )

    # Human reviews table
    op.create_table(
        'human_reviews',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reviewer_id', sa.CHAR(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('relevance_decision', sa.String(50), nullable=False),
        sa.Column('pursue_decision', sa.String(50), nullable=False),
        sa.Column('comments', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Notifications table
    op.create_table(
        'notifications',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('bid_id', sa.CHAR(36), sa.ForeignKey('bids.id', ondelete='CASCADE'), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False),
        sa.Column('recipient', sa.String(255), nullable=False),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('deduplication_key', sa.String(255), index=True, nullable=True),
        sa.Column('status', sa.String(50), default='PENDING', nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Audit logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.CHAR(36), primary_key=True),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', sa.CHAR(36), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('notifications')
    op.drop_table('human_reviews')
    op.drop_table('bid_product_matches')
    op.drop_table('bid_scores')
    op.drop_table('bid_analysis')
    op.drop_table('bid_status_history')
    op.drop_table('bids')
    op.drop_table('raw_bid_payloads')
    op.drop_table('collection_runs')
    op.drop_table('product_categories')
    op.drop_table('product_technologies')
    op.drop_table('product_keywords')
    op.drop_table('product_capabilities')
    op.drop_table('products')
    op.drop_table('users')
