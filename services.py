from decimal import Decimal

from flask import current_app

from models import db, Bucket, Transaction, IncomeSource, RECURRING_UNITS
from datetime import date
from dateutil.relativedelta import relativedelta

ZERO = Decimal("0.00")

# Guard against an unbounded catch-up loop if a next_date is absurdly old.
MAX_CATCHUP_PERIODS = 520  # ~10 years of weekly income


class FinanceService:
    @staticmethod
    def _advance(source):
        """Move a recurring source's next_date forward by exactly one period.

        Returns False if the source does not recur (or has no date to advance),
        in which case the caller deactivates it.
        """
        if source.frequency_unit == 'one-off' or not source.next_date:
            return False

        delta = FinanceService.period_delta(source.frequency_unit, source.frequency_value)
        if delta is None:
            # Unknown unit. Do NOT fall through to the caller's deactivate
            # branch: an unrecognised unit is a data problem, and silently
            # switching off someone's salary is the worst possible response.
            return False

        source.next_date += delta
        return True

    @staticmethod
    def period_delta(unit, value=1):
        """relativedelta for 'every N <unit>', or None if the unit is unknown."""
        step = max(int(value or 1), 1)
        if unit == 'days':
            return relativedelta(days=step)
        if unit == 'weeks':
            return relativedelta(weeks=step)
        if unit == 'months':
            return relativedelta(months=step)
        if unit == 'years':
            return relativedelta(years=step)
        return None

    @staticmethod
    def _apply_once(source, user_id):
        """Distribute one payment of `source` across its rules. No commit."""
        savings = Bucket.query.filter_by(user_id=user_id, bucket_type='savings').first()
        remaining = Decimal(source.amount or 0)

        # 1. Process specific rules for THIS income source
        for rule in source.rules:
            if remaining <= ZERO:
                break
            bucket = rule.bucket
            if not bucket or bucket.user_id != user_id or bucket.is_archived:
                continue

            amount = Decimal(rule.amount or 0)

            # Top a goal up to its target rather than skipping or overshooting.
            if bucket.bucket_type == 'goal' and bucket.target_amount:
                headroom = Decimal(bucket.target_amount) - Decimal(bucket.balance or 0)
                if headroom <= ZERO:
                    continue
                amount = min(amount, headroom)

            transfer = min(amount, remaining)
            if transfer <= ZERO:
                continue

            bucket.balance = Decimal(bucket.balance or 0) + transfer
            remaining -= transfer
            db.session.add(Transaction(
                user_id=user_id, bucket_id=bucket.id, amount=transfer,
                note=f"Income Rule: {source.name}"[:100],
            ))

        # 2. Residual flows to user's Savings
        if remaining > ZERO and savings:
            savings.balance = Decimal(savings.balance or 0) + remaining
            db.session.add(Transaction(
                user_id=user_id, bucket_id=savings.id, amount=remaining,
                note=f"Residual from {source.name}"[:100],
            ))

    @staticmethod
    def process_income_source(user_id, source_id, catch_up=False):
        """Process an income source once, or repeatedly until it is current.

        catch_up=True is used by the automatic dashboard check: a source that is
        six weeks overdue pays out six times in one pass. Previously each page
        load advanced next_date by a single period, so catching up required six
        separate visits.
        """
        source = IncomeSource.query.filter_by(id=source_id, user_id=user_id).first()
        if not source:
            return 0

        unit = source.frequency_unit
        # Refuse to touch a source whose unit we do not recognise. Paying it
        # out would repeat on every dashboard load (next_date can never
        # advance), and deactivating it would silently switch off someone's
        # income over what is really a data problem. Do neither, and say so.
        if unit != 'one-off' and unit not in RECURRING_UNITS:
            current_app.logger.error(
                "Income source %s has unknown frequency_unit %r - skipped.",
                source.id, unit)
            return 0

        today = date.today()
        applied = 0

        while True:
            FinanceService._apply_once(source, user_id)
            applied += 1

            if not FinanceService._advance(source):
                # One-off, or recurring with no next_date set: pays out once
                # and then stops, so it cannot silently repeat forever.
                source.is_active = False
                break

            if not catch_up or source.next_date > today or applied >= MAX_CATCHUP_PERIODS:
                break

        db.session.commit()
        return applied

    @staticmethod
    def preview_allocation(source):
        """Work out where the next payment would land, without changing anything.

        Mirrors _apply_once so the Income page can show the split before it
        happens. Returns (rows, residual, savings_bucket) where rows is a list
        of (rule, bucket, amount, capped) - `capped` marks a rule trimmed
        because the goal would have overshot its target. The rule is included
        so the template can build a delete link without having to match rules
        back to buckets (two rules may target the same bucket).
        """
        savings = Bucket.query.filter_by(
            user_id=source.user_id, bucket_type='savings').first()
        remaining = Decimal(source.amount or 0)
        rows = []

        for rule in source.rules:
            bucket = rule.bucket
            if not bucket or bucket.user_id != source.user_id or bucket.is_archived:
                continue
            if remaining <= ZERO:
                rows.append((rule, bucket, ZERO, False))
                continue

            amount = Decimal(rule.amount or 0)
            capped = False
            if bucket.bucket_type == 'goal' and bucket.target_amount:
                headroom = Decimal(bucket.target_amount) - Decimal(bucket.balance or 0)
                if headroom <= ZERO:
                    rows.append((rule, bucket, ZERO, True))
                    continue
                if amount > headroom:
                    amount, capped = headroom, True

            transfer = min(amount, remaining)
            remaining -= transfer
            rows.append((rule, bucket, transfer, capped))

        return rows, remaining, savings

    @staticmethod
    def upcoming_dates(source, count=3):
        """The next few payment dates, for showing a schedule in the UI."""
        if not source.next_date or source.frequency_unit == 'one-off':
            return [source.next_date] if source.next_date else []
        delta = FinanceService.period_delta(source.frequency_unit, source.frequency_value)
        if delta is None:
            return [source.next_date]
        out, d = [], source.next_date
        for _ in range(count):
            out.append(d)
            d = d + delta
        return out

    @staticmethod
    def log_spend(user_id, bucket_id, amount, note):
        target = Bucket.query.filter_by(id=bucket_id, user_id=user_id).first()
        if not target:
            return False

        amount = Decimal(amount)
        # Balances are allowed to go negative by design (see commit f6bc00b).
        target.balance = Decimal(target.balance or 0) - amount
        db.session.add(Transaction(
            user_id=user_id, bucket_id=bucket_id, amount=-amount, note=note[:100],
        ))
        db.session.commit()
        return True

    @staticmethod
    def transfer_money(user_id, from_id, to_id, amount, note):
        source = Bucket.query.filter_by(id=from_id, user_id=user_id).first()
        dest = Bucket.query.filter_by(id=to_id, user_id=user_id).first()

        if not source or not dest or source.id == dest.id:
            return False

        amount = Decimal(amount)
        # Deliberately no 'source.balance >= amount' check - overdrawing is allowed.
        source.balance = Decimal(source.balance or 0) - amount
        dest.balance = Decimal(dest.balance or 0) + amount

        # Double entry log
        db.session.add(Transaction(
            user_id=user_id, bucket_id=source.id, amount=-amount,
            note=f"To {dest.name}: {note}"[:100],
        ))
        db.session.add(Transaction(
            user_id=user_id, bucket_id=dest.id, amount=amount,
            note=f"From {source.name}: {note}"[:100],
        ))
        db.session.commit()
        return True

    @staticmethod
    def finalize_goal(user_id, goal_id, actual_cost):
        goal = Bucket.query.filter_by(id=goal_id, user_id=user_id).first()
        savings = Bucket.query.filter_by(user_id=user_id, bucket_type='savings').first()

        if not goal or not savings:
            return False

        actual_cost = Decimal(actual_cost)
        balance = Decimal(goal.balance or 0)

        # Log the goal's own outflow. Without this the ledger showed money
        # flowing into a goal and never leaving it, and any shortfall or
        # leftover vanished with no record.
        if balance != ZERO:
            db.session.add(Transaction(
                user_id=user_id, bucket_id=goal.id, amount=-balance,
                note=f"Goal completed: {goal.name} (paid {actual_cost})"[:100],
            ))

        leftover = balance - actual_cost
        if leftover > ZERO:
            savings.balance = Decimal(savings.balance or 0) + leftover
            db.session.add(Transaction(
                user_id=user_id, bucket_id=savings.id, amount=leftover,
                note=f"Leftover from goal: {goal.name}"[:100],
            ))
        elif leftover < ZERO:
            # Goal cost more than it held: the shortfall comes out of Savings
            # so the books stay balanced instead of the money appearing free.
            shortfall = -leftover
            savings.balance = Decimal(savings.balance or 0) - shortfall
            db.session.add(Transaction(
                user_id=user_id, bucket_id=savings.id, amount=-shortfall,
                note=f"Shortfall on goal: {goal.name}"[:100],
            ))

        goal.balance = ZERO
        goal.is_archived = True
        db.session.commit()
        return True

    @staticmethod
    def check_recurring_income(user_id):
        today = date.today()
        # Only process pending income belonging to THIS user
        pending = IncomeSource.query.filter(
            IncomeSource.user_id == user_id,
            IncomeSource.next_date != None,  # noqa: E711 - SQL NULL check
            IncomeSource.next_date <= today,
            IncomeSource.is_active == True,  # noqa: E712
            IncomeSource.frequency_unit != 'one-off',
        ).all()

        for source in pending:
            FinanceService.process_income_source(user_id, source.id, catch_up=True)
