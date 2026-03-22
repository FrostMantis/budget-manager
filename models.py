from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Bucket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    # Types: 'standard', 'everything', 'savings', 'goal'
    bucket_type = db.Column(db.String(20), default='standard')
    balance = db.Column(db.Float, default=0.0)
    target_amount = db.Column(db.Float, nullable=True)
    is_archived = db.Column(db.Boolean, default=False)
    # Relationships
    rules = db.relationship('AllocationRule', backref='bucket', cascade="all, delete-orphan")
    transactions = db.relationship('Transaction', backref='bucket', lazy=True)

class IncomeSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    next_date = db.Column(db.Date, nullable=True) 
    # Frequency: 'one-off', 'days', 'weeks', 'months'
    frequency_unit = db.Column(db.String(10), default='one-off')
    frequency_value = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    # Relationship to specific rules for this source
    rules = db.relationship('AllocationRule', backref='source', cascade="all, delete-orphan")

class AllocationRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    income_source_id = db.Column(db.Integer, db.ForeignKey('income_source.id'), nullable=False)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=False)
    amount = db.Column(db.Float, default=0.0)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)