"""Baseline: the schema as it already exists in production.

This revision describes the CURRENT production schema (money columns still
Float). It exists so Alembic has a starting point to chain from.

On an existing database (production, or your local copy) do NOT run this --
run `flask db stamp 0001_baseline` instead, which records "this database is
already at this revision" without touching any tables. Only a brand-new,
empty database should actually execute the upgrade below.

Revision ID: 0001_baseline
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )
    op.create_table(
        'bucket',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('bucket_type', sa.String(length=20), nullable=True),
        sa.Column('balance', sa.Float(), nullable=True),
        sa.Column('target_amount', sa.Float(), nullable=True),
        sa.Column('is_archived', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'income_source',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('next_date', sa.Date(), nullable=True),
        sa.Column('frequency_unit', sa.String(length=10), nullable=True),
        sa.Column('frequency_value', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'allocation_rule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('income_source_id', sa.Integer(), nullable=False),
        sa.Column('bucket_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['bucket_id'], ['bucket.id']),
        sa.ForeignKeyConstraint(['income_source_id'], ['income_source.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('bucket_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('note', sa.String(length=100), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['bucket_id'], ['bucket.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('transaction')
    op.drop_table('allocation_rule')
    op.drop_table('income_source')
    op.drop_table('bucket')
    op.drop_table('user')
