from models import db, Bucket, Transaction, AllocationRule, IncomeSource
from datetime import date
from dateutil.relativedelta import relativedelta

class FinanceService:
    @staticmethod
    def process_income_source(source_id):
        source = IncomeSource.query.get(source_id)
        if not source:
            return
            
        savings = Bucket.query.filter_by(bucket_type='savings').first()
        remaining = source.amount
        
        # 1. Process specific rules for THIS income source
        for rule in source.rules:
            bucket = Bucket.query.get(rule.bucket_id)
            if bucket.is_archived:
                continue
            
            # If goal is met, skip allocation so it flows to savings
            if bucket.bucket_type == 'goal' and bucket.target_amount and bucket.balance >= bucket.target_amount:
                continue
                
            transfer = min(rule.amount, remaining)
            bucket.balance += transfer
            remaining -= transfer
            db.session.add(Transaction(bucket_id=bucket.id, amount=transfer, note=f"Income Rule: {source.name}"))
        
        # 2. Leftovers go to Savings
        if remaining > 0:
            savings.balance += remaining
            db.session.add(Transaction(bucket_id=savings.id, amount=remaining, note=f"Residual from {source.name}"))
        
        # 3. Handle recurrence
        if source.frequency_unit != 'one-off' and source.next_date:
            if source.frequency_unit == 'days':
                source.next_date += relativedelta(days=source.frequency_value)
            elif source.frequency_unit == 'weeks':
                source.next_date += relativedelta(weeks=source.frequency_value)
            elif source.frequency_unit == 'months':
                source.next_date += relativedelta(months=source.frequency_value)
        else:
            source.is_active = False # Mark one-off as processed
            
        db.session.commit()

    @staticmethod
    def log_spend(bucket_id, amount, note):
        target = Bucket.query.get(bucket_id)
        everything = Bucket.query.filter_by(bucket_type='everything').first()

        if target.balance >= amount:
            target.balance -= amount
        else:
            # Failover logic
            shortfall = amount - target.balance
            target.balance = 0
            everything.balance -= shortfall 
        
        db.session.add(Transaction(bucket_id=bucket_id, amount=-amount, note=note))
        db.session.commit()

    @staticmethod
    def transfer_money(from_id, to_id, amount, note):
        source = Bucket.query.get(from_id)
        dest = Bucket.query.get(to_id)
        
        if source.balance >= amount:
            source.balance -= amount
            dest.balance += amount
            
            db.session.add(Transaction(bucket_id=source.id, amount=-amount, note=f"Transfer to {dest.name}: {note}"))
            db.session.add(Transaction(bucket_id=dest.id, amount=amount, note=f"Transfer from {source.name}: {note}"))
            db.session.commit()
            return True
        return False

    @staticmethod
    def finalize_goal(goal_id, actual_cost):
        goal = Bucket.query.get(goal_id)
        savings = Bucket.query.filter_by(bucket_type='savings').first()
        
        leftover = goal.balance - actual_cost
        if leftover > 0:
            savings.balance += leftover
            db.session.add(Transaction(bucket_id=savings.id, amount=leftover, note=f"Leftover from {goal.name} archive"))
            
        goal.balance = 0
        goal.is_archived = True
        db.session.commit()

    @staticmethod
    def check_recurring_income():
        today = date.today()
        pending = IncomeSource.query.filter(
            IncomeSource.next_date <= today, 
            IncomeSource.is_active == True,
            IncomeSource.frequency_unit != 'one-off'
        ).all()
        for source in pending:
            FinanceService.process_income_source(source.id)