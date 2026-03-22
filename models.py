from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

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
    bucket_type = db.Column(db.String(20), default='standard') # savings, everything, standard, goal
    balance = db.Column(db.Float, default=0.0)
    target_amount = db.Column(db.Float, nullable=True)
    is_archived = db.Column(db.Boolean, default=False)
    transactions = db.relationship('Transaction', backref='bucket', lazy=True)

class IncomeSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    next_date = db.Column(db.Date, nullable=True)
    frequency_unit = db.Column(db.String(10), default='one-off')
    frequency_value = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    rules = db.relationship('AllocationRule', backref='source', cascade="all, delete-orphan")

class AllocationRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    income_source_id = db.Column(db.Integer, db.ForeignKey('income_source.id'), nullable=False)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    bucket = db.relationship('Bucket', backref='rules')

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bucket_id = db.Column(db.Integer, db.ForeignKey('bucket.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)