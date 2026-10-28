"""Gateway checkout records: a pack is credited only after a verified payment.

Revision ID: 0006_payments
Revises: 0005_credits
Create Date: 2026-10-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_payments"
down_revision = "0005_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("pack_id", sa.String(length=40), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column(
            "provider", sa.String(length=20), nullable=False, server_default="razorpay"
        ),
        sa.Column("provider_order_id", sa.String(length=120), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=120), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="created"
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_order_id"),
        sa.UniqueConstraint("provider_payment_id"),
    )
    op.create_index(op.f("ix_payments_org_id"), "payments", ["org_id"])
    op.create_index(
        op.f("ix_payments_provider_order_id"), "payments", ["provider_order_id"]
    )
    op.create_index(
        op.f("ix_payments_provider_payment_id"), "payments", ["provider_payment_id"]
    )
    op.create_index("ix_payments_org_created", "payments", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_payments_org_created", table_name="payments")
    op.drop_index(op.f("ix_payments_provider_payment_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_provider_order_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_org_id"), table_name="payments")
    op.drop_table("payments")
