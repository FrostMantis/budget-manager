from models import db, Bucket, Transaction, AllocationRule, IncomeSource
from datetime import date
from dateutil.relativedelta import relativedelta

class FinanceService:
    @staticmethod
    def process_income_source(user_id, source_id):
        # Ensure the source belongs to the user
        source = IncomeSource.query.filter_by(id=source_id, user_id=user_id).first()
        if not source:
            return
            
        savings = Bucket.query.filter_by(user_id=user_id, bucket_type='savings').first()
        remaining = source.amount
        
        # 1. Process specific rules for THIS income source
        for rule in source.rules:
            bucket = Bucket.query.get(rule.bucket_id)
            if not bucket or bucket.user_id != user_id or bucket.is_archived:
                continue
            
            # Skip if goal is already met
            if bucket.bucket_type == 'goal' and bucket.target_amount and bucket.balance >= bucket.target_amount:
                continue
                
            transfer = min(rule.amount, remaining)
            bucket.balance += transfer
            remaining -= transfer
            db.session.add(Transaction(user_id=user_id, bucket_id=bucket.id, amount=transfer, note=f"Income Rule: {source.name}"))
        
        # 2. Residual flows to user's Savings
        if remaining > 0 and savings:
            savings.balance += remaining
            db.session.add(Transaction(user_id=user_id, bucket_id=savings.id, amount=remaining, note=f"Residual from {source.name}"))
        
        # 3. Handle recurrence logic
        if source.frequency_unit != 'one-off' and source.next_date:
            if source.frequency_unit == 'weeks':
                source.next_date += relativedelta(weeks=1)
            elif source.frequency_unit == 'months':
                source.next_date += relativedelta(months=1)
        else:
            source.is_active = False # One-off sources deactivate after processing
            
        db.session.commit()

    @staticmethod
    def log_spend(user_id, bucket_id, amount, note):
        target = Bucket.query.filter_by(id=bucket_id, user_id=user_id).first()
        if not target:
            return

        # Simplified: Always subtract the amount, allowing negative balance
        target.balance -= amount
        
        db.session.add(Transaction(user_id=user_id, bucket_id=bucket_id, amount=-amount, note=note))
        db.session.commit()

    @staticmethod
    def transfer_money(user_id, from_id, to_id, amount, note):
        source = Bucket.query.filter_by(id=from_id, user_id=user_id).first()
        dest = Bucket.query.filter_by(id=to_id, user_id=user_id).first()
        
        # Removed the check: 'if source.balance >= amount'
        if source and dest:
            source.balance -= amount
            dest.balance += amount
            
            # Double entry log
            db.session.add(Transaction(user_id=user_id, bucket_id=source.id, amount=-amount, note=f"To {dest.name}: {note}"))
            db.session.add(Transaction(user_id=user_id, bucket_id=dest.id, amount=amount, note=f"From {source.name}: {note}"))
            db.session.commit()
            return True
        return False

    @staticmethod
    def finalize_goal(user_id, goal_id, actual_cost):
        goal = Bucket.query.filter_by(id=goal_id, user_id=user_id).first()
        savings = Bucket.query.filter_by(user_id=user_id, bucket_type='savings').first()
        
        if not goal or not savings:
            return

        leftover = goal.balance - actual_cost
        if leftover > 0:
            savings.balance += leftover
            db.session.add(Transaction(user_id=user_id, bucket_id=savings.id, amount=leftover, note=f"Leftover from goal: {goal.name}"))
            
        goal.balance = 0
        goal.is_archived = True
        db.session.commit()

    @staticmethod
    def check_recurring_income(user_id):
        today = date.today()
        # Only process pending income belonging to THIS user
        pending = IncomeSource.query.filter(
            IncomeSource.user_id == user_id,
            IncomeSource.next_date <= today, 
            IncomeSource.is_active == True,
            IncomeSource.frequency_unit != 'one-off'
        ).all()
        
        for source in pending:
            FinanceService.process_income_source(user_id, source.id)