"""SaaS business layer: plan periods, GST invoices, invites, password resets.

Revision ID: 0007_saas_business
Revises: 0006_payments
Create Date: 2026-10-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_saas_business"
down_revision = "0006_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Billing profile snapshot, used as the buyer block on invoices.
    op.add_column(
        "organizations",
        sa.Column("legal_name", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "organizations",
        sa.Column("gstin", sa.String(length=20), nullable=False, server_default=""),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "billing_email", sa.String(length=255), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("billing_address", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "billing_state", sa.String(length=100), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "organizations",
        sa.Column("low_balance_alerted_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("included_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_paise", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("provider_order_id", sa.String(length=120), nullable=True),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reminder_sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscriptions_org_id"), "subscriptions", ["org_id"])
    op.create_index(
        op.f("ix_subscriptions_provider_order_id"),
        "subscriptions",
        ["provider_order_id"],
    )
    op.create_index(
        "ix_subscriptions_org_period", "subscriptions", ["org_id", "period_end"]
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("subtotal_paise", sa.Integer(), nullable=False),
        sa.Column("gst_paise", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column(
            "customer_gstin", sa.String(length=20), nullable=False, server_default=""
        ),
        sa.Column("customer_address", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "customer_state", sa.String(length=100), nullable=False, server_default=""
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_index(op.f("ix_invoices_org_id"), "invoices", ["org_id"])
    op.create_index("ix_invoices_org_issued", "invoices", ["org_id", "issued_at"])

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_invites_org_id"), "invites", ["org_id"])
    op.create_index(op.f("ix_invites_email"), "invites", ["email"])
    op.create_index(op.f("ix_invites_token_hash"), "invites", ["token_hash"])
    op.create_index("ix_invites_org_email", "invites", ["org_id", "email"])

    op.create_table(
        "password_resets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_password_resets_user_id"), "password_resets", ["user_id"])
    op.create_index(
        op.f("ix_password_resets_token_hash"), "password_resets", ["token_hash"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_password_resets_token_hash"), table_name="password_resets")
    op.drop_index(op.f("ix_password_resets_user_id"), table_name="password_resets")
    op.drop_table("password_resets")

    op.drop_index("ix_invites_org_email", table_name="invites")
    op.drop_index(op.f("ix_invites_token_hash"), table_name="invites")
    op.drop_index(op.f("ix_invites_email"), table_name="invites")
    op.drop_index(op.f("ix_invites_org_id"), table_name="invites")
    op.drop_table("invites")

    op.drop_index("ix_invoices_org_issued", table_name="invoices")
    op.drop_index(op.f("ix_invoices_org_id"), table_name="invoices")
    op.drop_table("invoices")

    op.drop_index("ix_subscriptions_org_period", table_name="subscriptions")
    op.drop_index(
        op.f("ix_subscriptions_provider_order_id"), table_name="subscriptions"
    )
    op.drop_index(op.f("ix_subscriptions_org_id"), table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_column("organizations", "low_balance_alerted_at")
    op.drop_column("organizations", "billing_state")
    op.drop_column("organizations", "billing_address")
    op.drop_column("organizations", "billing_email")
    op.drop_column("organizations", "gstin")
    op.drop_column("organizations", "legal_name")
