"""auth hardening: revoked_tokens, login_attempts, user lockout columns

Revision ID: 0007_auth_hardening
Revises: 0006_bid_matching_status
Create Date: 2026-11-07 00:00:00.000000

Adds:
- revoked_tokens table: JWT JTI revocation for secure logout
- login_attempts table: brute-force / failed-login audit trail
- users.failed_login_attempts: consecutive failure counter
- users.locked_until: account lockout timestamp

All changes are reversible (downgrade drops the columns and tables).
Existing records are preserved.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_auth_hardening"
down_revision: Union[str, None] = "0006_bid_matching_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # revoked_tokens: JWT JTI blacklist for secure logout / revocation
    # ------------------------------------------------------------------
    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("jti", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column(
            "user_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Index("ix_revoked_tokens_user_expires", "user_id", "expires_at"),
    )

    # ------------------------------------------------------------------
    # login_attempts: brute-force detection audit trail
    # ------------------------------------------------------------------
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, index=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Index("ix_login_attempts_email_attempted", "email", "attempted_at"),
        sa.Index("ix_login_attempts_ip_attempted", "ip_address", "attempted_at"),
    )

    # ------------------------------------------------------------------
    # users.failed_login_attempts + users.locked_until
    # ------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Reverse the users columns first (no dependencies).
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")

    # Drop the new tables.
    op.drop_table("login_attempts")
    op.drop_table("revoked_tokens")
