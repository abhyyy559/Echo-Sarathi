"""Provider usage snapshots for the /dev quota dashboard.

Revision ID: 0004_usage_snapshots
Revises: 0003_calls_context
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_usage_snapshots"
down_revision = "0003_calls_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("key_id", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("metric", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usage_snapshots_provider"), "usage_snapshots", ["provider"])
    op.create_index(op.f("ix_usage_snapshots_key_id"), "usage_snapshots", ["key_id"])
    op.create_index(op.f("ix_usage_snapshots_metric"), "usage_snapshots", ["metric"])
    op.create_index(op.f("ix_usage_snapshots_timestamp"), "usage_snapshots", ["timestamp"])
    op.create_index(
        "ix_usage_provider_timestamp", "usage_snapshots", ["provider", "timestamp"]
    )
    op.create_index(
        "ix_usage_key_model_metric", "usage_snapshots", ["key_id", "model", "metric"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_key_model_metric", table_name="usage_snapshots")
    op.drop_index("ix_usage_provider_timestamp", table_name="usage_snapshots")
    op.drop_index(op.f("ix_usage_snapshots_timestamp"), table_name="usage_snapshots")
    op.drop_index(op.f("ix_usage_snapshots_metric"), table_name="usage_snapshots")
    op.drop_index(op.f("ix_usage_snapshots_key_id"), table_name="usage_snapshots")
    op.drop_index(op.f("ix_usage_snapshots_provider"), table_name="usage_snapshots")
    op.drop_table("usage_snapshots")
