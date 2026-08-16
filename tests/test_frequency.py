"""Granular income frequency: 'every N days/weeks/months/years'."""
import os
import re
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402
from app import create_app  # noqa: E402
from models import db, User, Bucket, IncomeSource, AllocationRule, Transaction  # noqa: E402
from services import FinanceService  # noqa: E402

app = create_app()
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


def reset():
    with app.app_context():
        Transaction.query.delete()
        AllocationRule.query.delete()
        IncomeSource.query.delete()
        Bucket.query.delete()
        User.query.delete()
        u = User(username="alice", password_hash=generate_password_hash("pw"))
        db.session.add(u)
        db.session.flush()
        db.session.add_all([
            Bucket(user_id=u.id, name="Savings", bucket_type="savings", balance=0),
            Bucket(user_id=u.id, name="Everything", bucket_type="everything", balance=0),
            Bucket(user_id=u.id, name="Groceries", bucket_type="standard", balance=0),
        ])
        db.session.commit()
        return u.id


def add_source(uid, unit, value, next_date, amount="100.00"):
    src = IncomeSource(user_id=uid, name=f"{unit}-{value}", amount=Decimal(amount),
                       frequency_unit=unit, frequency_value=value,
                       next_date=next_date, is_active=True)
    db.session.add(src)
    db.session.commit()
    return src


# ------------------------------------------------- period arithmetic
with app.app_context():
    pd = FinanceService.period_delta
    start = date(2026, 1, 15)
    cases = [
        ("every 1 day",     "days",   1,  date(2026, 1, 16)),
        ("every 10 days",   "days",   10, date(2026, 1, 25)),
        ("every 2 weeks",   "weeks",  2,  date(2026, 1, 29)),
        ("every 4 weeks",   "weeks",  4,  date(2026, 2, 12)),
        ("every 1 month",   "months", 1,  date(2026, 2, 15)),
        ("every 3 months",  "months", 3,  date(2026, 4, 15)),
        ("every 1 year",    "years",  1,  date(2027, 1, 15)),
    ]
    for label, unit, val, expected in cases:
        got = start + pd(unit, val)
        check(f"{label} -> {expected}", got == expected, f"got {got}")

    check("unknown unit yields no delta", pd("fortnights", 1) is None)
    # month-end behaviour is relativedelta's, but worth pinning down
    check("31 Jan + 1 month clamps to 28 Feb",
          date(2026, 1, 31) + pd("months", 1) == date(2026, 2, 28),
          f"got {date(2026, 1, 31) + pd('months', 1)}")

# ------------------------------------------------- catch-up honours interval
uid = reset()
with app.app_context():
    # Paid every 2 weeks, last due 6 weeks ago => due at -6w, -4w, -2w, 0 = 4
    src = add_source(uid, "weeks", 2, date.today() - timedelta(weeks=6))
    FinanceService.check_recurring_income(uid)
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    src = db.session.get(IncomeSource, src.id)
check("fortnightly, 6 weeks overdue -> 4 payments",
      savings.balance == Decimal("400.00"), f"balance={savings.balance}")
check("  -> next_date is in the future", src.next_date > date.today(), f"{src.next_date}")

uid = reset()
with app.app_context():
    # Every 10 days, 25 days overdue => due at -25, -15, -5 = 3 (next at +5)
    src = add_source(uid, "days", 10, date.today() - timedelta(days=25))
    FinanceService.check_recurring_income(uid)
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    src = db.session.get(IncomeSource, src.id)
check("every 10 days, 25 days overdue -> 3 payments",
      savings.balance == Decimal("300.00"), f"balance={savings.balance}")
check("  -> next_date 5 days out", src.next_date == date.today() + timedelta(days=5), f"{src.next_date}")

uid = reset()
with app.app_context():
    src = add_source(uid, "years", 1, date.today() - timedelta(days=1))
    FinanceService.check_recurring_income(uid)
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
check("yearly, 1 day overdue -> exactly 1 payment",
      savings.balance == Decimal("100.00"), f"balance={savings.balance}")

# ------------------------------- unknown unit is inert, not destructive
uid = reset()
with app.app_context():
    src = add_source(uid, "fortnights", 1, date.today() - timedelta(days=30))
    sid = src.id
    FinanceService.check_recurring_income(uid)
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    src = db.session.get(IncomeSource, sid)
check("unknown unit pays nothing", savings.balance == Decimal("0.00"), f"{savings.balance}")
check("unknown unit is NOT deactivated", src.is_active is True, f"is_active={src.is_active}")
check("unknown unit leaves next_date alone",
      src.next_date == date.today() - timedelta(days=30), f"{src.next_date}")

# ------------------------------------------------- allocation preview
uid = reset()
with app.app_context():
    gr = Bucket.query.filter_by(user_id=uid, bucket_type="standard").first()
    goal = Bucket(user_id=uid, name="Bike", bucket_type="goal",
                  balance=Decimal("880.00"), target_amount=Decimal("900.00"))
    db.session.add(goal)
    db.session.flush()
    src = IncomeSource(user_id=uid, name="Salary", amount=Decimal("1000.00"),
                       frequency_unit="months", frequency_value=1,
                       next_date=date.today() + timedelta(days=5), is_active=True)
    db.session.add(src)
    db.session.flush()
    db.session.add(AllocationRule(income_source_id=src.id, bucket_id=gr.id, amount=Decimal("200.00")))
    # asks for 100 but the goal only has 20 of headroom
    db.session.add(AllocationRule(income_source_id=src.id, bucket_id=goal.id, amount=Decimal("100.00")))
    db.session.commit()

    rows, residual, savings = FinanceService.preview_allocation(src)
    amounts = {b.name: a for (_r, b, a, _c) in rows}
    capped = {b.name: c for (_r, b, _a, c) in rows}
    before = {b.name: b.balance for b in Bucket.query.filter_by(user_id=uid).all()}

check("preview: plain rule shows its full amount", amounts.get("Groceries") == Decimal("200.00"), str(amounts))
check("preview: goal rule capped to headroom", amounts.get("Bike") == Decimal("20.00"), str(amounts))
check("preview: capped flag set", capped.get("Bike") is True, str(capped))
check("preview: residual is the rest", residual == Decimal("780.00"), f"residual={residual}")
check("preview: total equals income", sum(amounts.values()) + residual == Decimal("1000.00"))

with app.app_context():
    after = {b.name: b.balance for b in Bucket.query.filter_by(user_id=uid).all()}
check("preview changes nothing", before == after, f"{before} != {after}")

# preview must match what actually happens
with app.app_context():
    src = IncomeSource.query.filter_by(user_id=uid).first()
    FinanceService.process_income_source(uid, src.id)
    real = {b.name: b.balance for b in Bucket.query.filter_by(user_id=uid).all()}
check("preview matched reality: Groceries", real["Groceries"] == Decimal("200.00"), str(real))
check("preview matched reality: Bike", real["Bike"] == Decimal("900.00"), str(real))
check("preview matched reality: Savings", real["Savings"] == Decimal("780.00"), str(real))

# ------------------------------------------------- through the UI
uid = reset()
with app.test_client() as c:
    tok = re.search(r'name="csrf_token" value="([^"]+)"',
                    c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "alice", "password": "pw", "csrf_token": tok})
    tok = re.search(r'name="csrf_token" value="([^"]+)"',
                    c.get("/income").get_data(as_text=True)).group(1)

    c.post("/create-income-source", data={
        "name": "Fortnightly wage", "amount": "500", "unit": "weeks", "every": "2",
        "start_date": (date.today() + timedelta(days=3)).isoformat(),
        "csrf_token": tok}, follow_redirects=True)
    with app.app_context():
        s = IncomeSource.query.filter_by(user_id=uid, name="Fortnightly wage").first()
    check("UI create stores frequency_value=2",
          s is not None and s.frequency_value == 2 and s.frequency_unit == "weeks",
          f"unit={getattr(s,'frequency_unit',None)} value={getattr(s,'frequency_value',None)}")

    r = c.get("/income")
    check("income page shows 'Every 2 weeks'", "Every 2 weeks" in r.get_data(as_text=True))

    c.post(f"/edit-income-source/{s.id}", data={
        "name": "Fortnightly wage", "amount": "500", "unit": "days", "every": "10",
        "next_date": (date.today() + timedelta(days=3)).isoformat(),
        "csrf_token": tok}, follow_redirects=True)
    with app.app_context():
        s2 = db.session.get(IncomeSource, s.id)
    check("UI edit updates unit+interval",
          s2.frequency_unit == "days" and s2.frequency_value == 10,
          f"unit={s2.frequency_unit} value={s2.frequency_value}")

    # one-off must not keep a stale interval
    c.post(f"/edit-income-source/{s.id}", data={
        "name": "Fortnightly wage", "amount": "500", "unit": "one-off", "every": "10",
        "csrf_token": tok}, follow_redirects=True)
    with app.app_context():
        s3 = db.session.get(IncomeSource, s.id)
    check("one-off resets interval to 1", s3.frequency_value == 1, f"value={s3.frequency_value}")

    # out-of-range interval is rejected, not stored
    r = c.post("/create-income-source", data={
        "name": "Bad", "amount": "10", "unit": "weeks", "every": "9999",
        "csrf_token": tok}, follow_redirects=True)
    with app.app_context():
        bad = IncomeSource.query.filter_by(user_id=uid, name="Bad").first()
    check("out-of-range interval rejected", bad is None and r.status_code == 200)
    check("  -> and explained to the user", "between 1 and 366" in r.get_data(as_text=True))

failed = [n for n, ok in results if not ok]
print("\n" + "=" * 60)
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
