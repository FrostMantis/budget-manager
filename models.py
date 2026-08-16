from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone

db = SQLAlchemy()

# Money is Numeric(10, 2), not Float: repeated float add/subtract drifts, and
# these columns are added to and subtracted from on every spend and transfer.
# Reads come back as decimal.Decimal - see forms.parse_amount.
MONEY = db.Numeric(10, 2)

BUCKET_TYPES = ('savings', 'everything', 'standard', 'goal')
SYSTEM_BUCKET_TYPES = ('savings', 'everything')

# 'days' and 'years' are new; 'one-off', 'weeks' and 'months' are the original
# three and must keep their exact spelling, since production rows store them.
# Paired with frequency_value ('every N <unit>'), which has been in the schema
# since the beginning but was never wired up.
FREQUENCY_UNITS = ('one-off', 'days', 'weeks', 'months', 'years')
RECURRING_UNITS = ('days', 'weeks', 'months', 'years')
MAX_FREQUENCY_VALUE = 366


def utcnow():
    """Timezone-aware UTC now. datetime.utcnow() is deprecated in 3.12+."""
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # Relationships
    buckets = db.relationship('Bucket', backref='owner', lazy=True)
    incomes = db.relationship('IncomeSource', backref='owner', lazy=True)


class Bucket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    bucket_type = db.Column(db.String(20), default='standard')  # savings, everything, standard, goal
    balance = db.Column(MONEY, default=0, nullable=False)
    target_amount = db.Column(MONEY, nullable=True)
    is_archived = db.Column(db.Boolean, default=False)

    # Transactions keep a nullable bucket_id, so deleting a bucket leaves the
    # ledger entries behind with bucket_id NULL (history.html renders that as
    # "N/A"). That is deliberate - history should survive the bucket.
    transactions = db.relationship('Transaction', backref='bucket', lazy=True)

    # Allocation rules must cascade. AllocationRule.bucket_id is NOT NULL, so
    # without this SQLAlchemy tries to NULL it on bucket delete and the request
    # dies with an IntegrityError.
    rules = db.relationship(
        'AllocationRule',
        backref='bucket',
        cascade='all, delete-orphan',
        passive_deletes=False,
    )


class IncomeSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    amount = db.Column(MONEY, nullable=False)
    next_date = db.Column(db.Date, nullable=True)
    frequency_unit = db.Column(db.String(10), default='one-off')
    frequency_value = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    rules = db.relationship('AllocationRule', backref='source', cascade="all, delete-orphan")


class AllocationRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    income_source_id = db.Column(db.Integer, db.ForeignKey('income_source.id'), nullable=False)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=False)
    amount = db.Column(MONEY, default=0, nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=True)
    amount = db.Column(MONEY, nullable=False)
    note = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=utcnow)
