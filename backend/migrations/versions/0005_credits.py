"""Prepaid credit wallet: balance column, ledger table, welcome credits.

Revision ID: 0005_credits
Revises: 0004_usage_snapshots
Create Date: 2026-10-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_credits"
down_revision = "0004_usage_snapshots"
branch_labels = None
depends_on = None

#: 10 minutes at the Rs 3.00 retail rate (see app/services/billing.py).
TRIAL_PAISE = 3000


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "credit_balance_paise",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("paid_paise", sa.Integer(), nullable=True),
        sa.Column("balance_after_paise", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credit_ledger_org_id"), "credit_ledger", ["org_id"])
    op.create_index(op.f("ix_credit_ledger_call_id"), "credit_ledger", ["call_id"])
    op.create_index(
        "ix_credit_ledger_org_created", "credit_ledger", ["org_id", "created_at"]
    )

    # Existing tenants start on the same welcome credit a new signup gets, so
    # campaigns already scheduled do not hit a zero wallet on upgrade.
    op.execute(
        sa.text(
            "INSERT INTO credit_ledger "
            "(org_id, kind, amount_paise, paid_paise, balance_after_paise, description) "
            "SELECT id, 'grant', :amount, 0, :amount, 'Welcome credit' FROM organizations"
        ).bindparams(amount=TRIAL_PAISE)
    )
    op.execute(
        sa.text("UPDATE organizations SET credit_balance_paise = :amount").bindparams(
            amount=TRIAL_PAISE
        )
    )


def downgrade() -> None:
    op.drop_index("ix_credit_ledger_org_created", table_name="credit_ledger")
    op.drop_index(op.f("ix_credit_ledger_call_id"), table_name="credit_ledger")
    op.drop_index(op.f("ix_credit_ledger_org_id"), table_name="credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_column("organizations", "credit_balance_paise")
