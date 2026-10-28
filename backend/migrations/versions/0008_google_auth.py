"""Google Sign-In: nullable password hash and linked Google subject id.

Revision ID: 0008_google_auth
Revises: 0007_saas_business
Create Date: 2026-10-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_google_auth"
down_revision = "0007_saas_business"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table keeps the SQLite test database working: SQLite cannot
    # drop NOT NULL in place, so Alembic recreates the table instead.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("google_sub", sa.String(length=255), nullable=True))
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.create_index(
            batch_op.f("ix_users_google_sub"), ["google_sub"], unique=True
        )


def downgrade() -> None:
    # Google-only users have no password; the old schema required one. An
    # empty hash fails bcrypt verification, so those accounts simply cannot
    # log in with a password after a downgrade.
    op.execute("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_google_sub"))
        batch_op.alter_column(
            "password_hash",
            existing_type=sa.String(length=255),
            nullable=False,
        )
        batch_op.drop_column("google_sub")
