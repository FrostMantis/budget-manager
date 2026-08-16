import os
import re
import sys
from datetime import date
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash
from app import create_app
from models import db, User, Bucket, IncomeSource, AllocationRule, Transaction

app = create_app()
with app.app_context():
    Transaction.query.delete(); AllocationRule.query.delete()
    IncomeSource.query.delete(); Bucket.query.delete(); User.query.delete()
    u = User(username="alice", password_hash=generate_password_hash("pw"))
    db.session.add(u); db.session.flush()
    sv = Bucket(user_id=u.id, name="Savings", bucket_type="savings", balance=Decimal("1200.00"))
    ev = Bucket(user_id=u.id, name="Everything", bucket_type="everything", balance=Decimal("300.00"))
    gr = Bucket(user_id=u.id, name="Groceries", bucket_type="standard", balance=Decimal("42.50"))
    g1 = Bucket(user_id=u.id, name="Bike", bucket_type="goal", balance=Decimal("150.00"), target_amount=Decimal("900.00"))
    g2 = Bucket(user_id=u.id, name="NoTarget", bucket_type="goal", balance=Decimal("10.00"), target_amount=None)
    db.session.add_all([sv,ev,gr,g1,g2]); db.session.flush()
    s = IncomeSource(user_id=u.id, name="Salary", amount=Decimal("2000.00"),
                     frequency_unit="months", frequency_value=1, next_date=date(2099,1,1), is_active=True)
    db.session.add(s); db.session.flush()
    db.session.add(AllocationRule(income_source_id=s.id, bucket_id=gr.id, amount=Decimal("200.00")))
    db.session.add(Transaction(user_id=u.id, bucket_id=gr.id, amount=Decimal("-12.34"), note="Coffee"))
    db.session.add(Transaction(user_id=u.id, bucket_id=None, amount=Decimal("5.00"), note="Orphan"))
    db.session.commit()

fail = 0
with app.test_client() as c:
    tok = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username":"alice","password":"pw","csrf_token":tok})
    for p in ["/", "/income", "/goals", "/manage", "/history"]:
        r = c.get(p)
        status = "PASS" if r.status_code == 200 else "FAIL"
        if r.status_code != 200: fail += 1
        print(f"{status}  GET {p} -> {r.status_code}")
print("ALL PAGES RENDER" if not fail else f"{fail} FAILED")
sys.exit(1 if fail else 0)
