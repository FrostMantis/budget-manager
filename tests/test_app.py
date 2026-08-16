"""Functional checks for the fixes, against the migrated MariaDB schema."""
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
    results.append((name, bool(cond), detail))
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


def login(client):
    r = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r = client.post("/login", data={"username": "alice", "password": "pw", "csrf_token": token})
    return r


def token_from(client, path):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


# ---------------------------------------------------------------- CSRF
uid = reset()
with app.test_client() as c:
    r = c.post("/login", data={"username": "alice", "password": "pw"})
    check("login without CSRF token is rejected", r.status_code == 400, f"got {r.status_code}")

with app.test_client() as c:
    r = login(c)
    check("login with CSRF token succeeds", r.status_code == 302 and r.headers["Location"].endswith("/"),
          f"{r.status_code} {r.headers.get('Location')}")

with app.test_client() as c:
    login(c)
    r = c.post("/spend", data={"bucket_id": 3, "amount": "5"})
    check("forged POST /spend rejected (no token)", r.status_code == 400, f"got {r.status_code}")

# --------------------------------------------------- destructive GET is gone
with app.test_client() as c:
    login(c)
    codes = {}
    with app.app_context():
        b = Bucket.query.filter_by(bucket_type="standard").first()
        bid = b.id
    for path in [f"/delete-bucket/{bid}", "/delete-transaction/1", "/delete-source/1",
                 "/delete-rule/1", "/process-now/1", "/logout"]:
        codes[path] = c.get(path).status_code
    check("destructive routes reject GET (405)", all(v == 405 for v in codes.values()), str(codes))

# ------------------------------------------- bucket delete with a rule attached
uid = reset()
with app.app_context():
    b = Bucket.query.filter_by(bucket_type="standard").first()
    src = IncomeSource(user_id=uid, name="Salary", amount=Decimal("100.00"),
                       frequency_unit="one-off", next_date=date.today())
    db.session.add(src)
    db.session.flush()
    db.session.add(AllocationRule(income_source_id=src.id, bucket_id=b.id, amount=Decimal("50.00")))
    db.session.add(Transaction(user_id=uid, bucket_id=b.id, amount=Decimal("-1.00"), note="old"))
    db.session.commit()
    bid = b.id

with app.test_client() as c:
    login(c)
    tok = token_from(c, "/manage")
    r = c.post(f"/delete-bucket/{bid}", data={"csrf_token": tok}, follow_redirects=True)
    ok = r.status_code == 200
with app.app_context():
    gone = db.session.get(Bucket, bid) is None
    rules_gone = AllocationRule.query.filter_by(bucket_id=bid).count() == 0
    tx_kept = Transaction.query.filter_by(note="old").first()
check("delete bucket w/ allocation rule does not 500", ok)
check("  -> bucket deleted and rule cascaded", gone and rules_gone, f"gone={gone} rules_gone={rules_gone}")
check("  -> ledger entry kept with NULL bucket", tx_kept is not None and tx_kept.bucket_id is None)

# --------------------------------------------------- recurring income catch-up
uid = reset()
with app.app_context():
    six_weeks_ago = date.today() - timedelta(weeks=6)
    db.session.add(IncomeSource(user_id=uid, name="Weekly", amount=Decimal("100.00"),
                                frequency_unit="weeks", frequency_value=1,
                                next_date=six_weeks_ago, is_active=True))
    db.session.commit()
    FinanceService.check_recurring_income(uid)
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    src = IncomeSource.query.filter_by(user_id=uid).first()
check("6-weeks-overdue income pays out 7x in one pass",
      savings.balance == Decimal("700.00"), f"balance={savings.balance}")
check("  -> next_date moved into the future", src.next_date > date.today(), f"next_date={src.next_date}")

# ------------------------------------------------------------ goal ledger
uid = reset()
with app.app_context():
    goal = Bucket(user_id=uid, name="Bike", bucket_type="goal",
                  balance=Decimal("500.00"), target_amount=Decimal("500.00"))
    db.session.add(goal)
    db.session.flush()
    # seed the balance WITH its ledger entry, so the books start balanced
    db.session.add(Transaction(user_id=uid, bucket_id=goal.id,
                               amount=Decimal("500.00"), note="seed"))
    db.session.commit()
    gid = goal.id
    FinanceService.finalize_goal(uid, gid, Decimal("450.00"))
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    total = db.session.query(db.func.sum(Transaction.amount)).filter_by(user_id=uid).scalar()
    balances = db.session.query(db.func.sum(Bucket.balance)).filter_by(user_id=uid).scalar()
check("goal leftover lands in savings", savings.balance == Decimal("50.00"), f"{savings.balance}")
check("goal completion is fully logged (ledger nets to bucket totals)",
      total == balances, f"ledger={total} buckets={balances}")

uid = reset()
with app.app_context():
    goal = Bucket(user_id=uid, name="Bike", bucket_type="goal",
                  balance=Decimal("500.00"), target_amount=Decimal("500.00"))
    db.session.add(goal)
    db.session.flush()
    db.session.add(Transaction(user_id=uid, bucket_id=goal.id,
                               amount=Decimal("500.00"), note="seed"))
    db.session.commit()
    FinanceService.finalize_goal(uid, goal.id, Decimal("620.00"))
    savings = Bucket.query.filter_by(user_id=uid, bucket_type="savings").first()
    total = db.session.query(db.func.sum(Transaction.amount)).filter_by(user_id=uid).scalar()
    balances = db.session.query(db.func.sum(Bucket.balance)).filter_by(user_id=uid).scalar()
check("goal overspend debits savings", savings.balance == Decimal("-120.00"), f"{savings.balance}")
check("  -> overspend is logged too", total == balances, f"ledger={total} buckets={balances}")

# ------------------------------------------------------- input validation
uid = reset()
with app.test_client() as c:
    login(c)
    tok = token_from(c, "/")
    with app.app_context():
        bid = Bucket.query.filter_by(bucket_type="standard").first().id
    r = c.post("/spend", data={"bucket_id": bid, "amount": "", "csrf_token": tok},
               follow_redirects=True)
    check("empty amount does not 500", r.status_code == 200, f"got {r.status_code}")
    check("  -> user sees an error", "required" in r.get_data(as_text=True).lower())

    r = c.post("/spend", data={"bucket_id": bid, "amount": "-50", "csrf_token": tok},
               follow_redirects=True)
    with app.app_context():
        bal = db.session.get(Bucket, bid).balance
    check("negative spend rejected (no free money)", bal == Decimal("0.00"), f"balance={bal}")

    r = c.post("/spend", data={"bucket_id": bid, "amount": "abc", "csrf_token": tok},
               follow_redirects=True)
    check("non-numeric amount does not 500", r.status_code == 200, f"got {r.status_code}")

    # bucket_type whitelist
    tok = token_from(c, "/manage")
    c.post("/create-bucket", data={"name": "Evil", "type": "savings", "csrf_token": tok},
           follow_redirects=True)
    with app.app_context():
        n = Bucket.query.filter_by(user_id=uid, bucket_type="savings").count()
    check("cannot forge a second savings bucket", n == 1, f"savings buckets={n}")

    # open redirect
    tok = token_from(c, "/manage")
    r = c.post(f"/update-balance/{bid}",
               data={"balance": "10", "next": "https://evil.example/x", "csrf_token": tok})
    check("open redirect blocked", r.headers["Location"] == "/manage", r.headers.get("Location", ""))

# ------------------------------------------------------- ownership isolation
with app.app_context():
    other = User(username="mallory", password_hash=generate_password_hash("pw"))
    db.session.add(other)
    db.session.commit()
    victim_bucket = Bucket.query.filter_by(bucket_type="standard").first().id
with app.test_client() as c:
    r = c.get("/login")
    tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    c.post("/login", data={"username": "mallory", "password": "pw", "csrf_token": tok})
    tok = token_from(c, "/manage")
    r = c.post(f"/delete-bucket/{victim_bucket}", data={"csrf_token": tok})
    check("cannot delete another user's bucket", r.status_code == 404, f"got {r.status_code}")

failed = [n for n, ok, _ in results if not ok]
print("\n" + "=" * 60)
print(f"{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
