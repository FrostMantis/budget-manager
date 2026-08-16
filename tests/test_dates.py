"""Dates are day-first everywhere. 03/04 is always 3 April, never 4 March."""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402
from app import create_app  # noqa: E402
from models import db, User, Bucket, IncomeSource, AllocationRule, Transaction  # noqa: E402
from routes import parse_date  # noqa: E402
from forms import InputError  # noqa: E402

app = create_app()
ok = []


def check(name, cond, detail=""):
    ok.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))

with app.app_context():
    # 03/04/2026 must be 3 April, never 4 March
    check("03/04/2026 parses as 3 April", parse_date("03/04/2026") == date(2026, 4, 3), str(parse_date("03/04/2026")))
    check("25/08/2026 parses", parse_date("25/08/2026") == date(2026, 8, 25))
    check("ISO still accepted", parse_date("2026-08-25") == date(2026, 8, 25))
    check("yyyy/mm/dd accepted", parse_date("2026/08/25") == date(2026, 8, 25))
    check("dd-mm-yyyy accepted", parse_date("25-08-2026") == date(2026, 8, 25))
    try:
        parse_date("08/25/2026"); r = False   # mm/dd: 25 is not a month
    except InputError:
        r = True
    check("mm/dd/yyyy rejected outright", r)
    try:
        parse_date("garbage"); r = False
    except InputError:
        r = True
    check("garbage rejected", r)

    Transaction.query.delete(); AllocationRule.query.delete()
    IncomeSource.query.delete(); Bucket.query.delete(); User.query.delete()
    u = User(username="d", password_hash=generate_password_hash("d")); db.session.add(u); db.session.flush()
    db.session.add(Bucket(user_id=u.id, name="Savings", bucket_type="savings", balance=0))
    db.session.commit(); uid = u.id

with app.test_client() as c:
    tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username":"d","password":"d","csrf_token":tok})
    tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/income").get_data(as_text=True)).group(1)
    c.post("/create-income-source", data={"name":"Wage","amount":"100","unit":"weeks","every":"2",
           "start_date":"03/04/2027","csrf_token":tok}, follow_redirects=True)
    with app.app_context():
        s = IncomeSource.query.filter_by(user_id=uid).first()
    check("form: typed 03/04/2027 stored as 3 April", s and s.next_date == date(2027,4,3), str(getattr(s,'next_date',None)))
    html = c.get("/income").get_data(as_text=True)
    check("page renders it as 03/04/2027", "03/04/2027" in html)
    check("no mm/dd anywhere on page", "04/03/2027" not in html)

    r = c.post("/create-income-source", data={"name":"Bad","amount":"10","unit":"weeks","every":"1",
               "start_date":"08/25/2026","csrf_token":tok}, follow_redirects=True)
    check("form rejects mm/dd/yyyy with a message", "day/month/year" in r.get_data(as_text=True).lower())

failed = [n for n, v in ok if not v]
print("\n" + "=" * 56)
print(f"{len(ok) - len(failed)}/{len(ok)} passed")
if failed:
    print("FAILED: " + "; ".join(failed))
sys.exit(1 if failed else 0)
