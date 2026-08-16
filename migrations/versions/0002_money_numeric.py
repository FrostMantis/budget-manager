"""Money columns: Float -> Numeric(10, 2).

Floats drift under repeated add/subtract, and these columns are added to and
subtracted from on every spend, transfer and income run. Numeric(10,2) stores
exact cents.

Existing values are converted by the database, which rounds to 2 decimals --
a balance stored as 10.999999999 becomes 11.00. That is the intended
correction, but it means the change is not perfectly reversible, so take a
dump before running this (see DEPLOY.md).

Also tightens two columns to NOT NULL. Any existing NULLs are backfilled to 0
first, otherwise MySQL rejects the ALTER.

Revision ID: 0002_money_numeric
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = '0002_money_numeric'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None

MONEY = sa.Numeric(precision=10, scale=2)


def upgrade():
    # Backfill NULLs before tightening nullability.
    op.execute("UPDATE bucket SET balance = 0 WHERE balance IS NULL")
    op.execute("UPDATE allocation_rule SET amount = 0 WHERE amount IS NULL")

    op.alter_column('bucket', 'balance',
                    existing_type=sa.Float(), type_=MONEY,
                    existing_nullable=True, nullable=False,
                    existing_server_default=None)
    op.alter_column('bucket', 'target_amount',
                    existing_type=sa.Float(), type_=MONEY,
                    existing_nullable=True)

    op.alter_column('income_source', 'amount',
                    existing_type=sa.Float(), type_=MONEY,
                    existing_nullable=False)

    op.alter_column('allocation_rule', 'amount',
                    existing_type=sa.Float(), type_=MONEY,
                    existing_nullable=True, nullable=False)

    op.alter_column('transaction', 'amount',
                    existing_type=sa.Float(), type_=MONEY,
                    existing_nullable=False)


def downgrade():
    op.alter_column('transaction', 'amount',
                    existing_type=MONEY, type_=sa.Float(),
                    existing_nullable=False)
    op.alter_column('allocation_rule', 'amount',
                    existing_type=MONEY, type_=sa.Float(),
                    existing_nullable=False, nullable=True)
    op.alter_column('income_source', 'amount',
                    existing_type=MONEY, type_=sa.Float(),
                    existing_nullable=False)
    op.alter_column('bucket', 'target_amount',
                    existing_type=MONEY, type_=sa.Float(),
                    existing_nullable=True)
    op.alter_column('bucket', 'balance',
                    existing_type=MONEY, type_=sa.Float(),
                    existing_nullable=False, nullable=True)
