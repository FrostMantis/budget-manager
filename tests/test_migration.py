"""Simulate the production upgrade: old schema + real data -> stamp -> upgrade.

Builds the PRE-change schema by hand (Float money columns, matching what is
live today), inserts representative rows including NULLs, then runs exactly
the commands DEPLOY.md tells you to run and asserts the data survived.
"""
import os
import subprocess
import sys
from decimal import Decimal

import sqlalchemy as sa

DB_URI = os.environ["DB_URI"]
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLASK = os.environ["FLASK_BIN"]

OLD_SCHEMA = [
    """CREATE TABLE user (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL)""",
    """CREATE TABLE bucket (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(50) NOT NULL,
        bucket_type VARCHAR(20),
        balance FLOAT,
        target_amount FLOAT,
        is_archived BOOL,
        FOREIGN KEY (user_id) REFERENCES user(id))""",
    """CREATE TABLE income_source (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(50) NOT NULL,
        amount FLOAT NOT NULL,
        next_date DATE,
        frequency_unit VARCHAR(10),
        frequency_value INT,
        is_active BOOL,
        FOREIGN KEY (user_id) REFERENCES user(id))""",
    """CREATE TABLE allocation_rule (
        id INT AUTO_INCREMENT PRIMARY KEY,
        income_source_id INT NOT NULL,
        bucket_id INT NOT NULL,
        amount FLOAT,
        FOREIGN KEY (income_source_id) REFERENCES income_source(id),
        FOREIGN KEY (bucket_id) REFERENCES bucket(id))""",
    """CREATE TABLE `transaction` (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        bucket_id INT,
        amount FLOAT NOT NULL,
        note VARCHAR(100),
        timestamp DATETIME,
        FOREIGN KEY (user_id) REFERENCES user(id),
        FOREIGN KEY (bucket_id) REFERENCES bucket(id))""",
]

SEED = [
    "INSERT INTO user (id, username, password_hash) VALUES (1, 'alice', 'x')",
    # A NULL balance and a NULL rule amount: the migration must backfill these
    # before it can add NOT NULL, which is the step most likely to fail on live data.
    "INSERT INTO bucket (id, user_id, name, bucket_type, balance, target_amount, is_archived)"
    " VALUES (1,1,'Savings','savings',1234.56,NULL,0),"
    "        (2,1,'Everything','everything',80.10,NULL,0),"
    "        (3,1,'Groceries','standard',NULL,NULL,0),"
    "        (4,1,'New Bike','goal',150.00,900.00,0)",
    "INSERT INTO income_source (id,user_id,name,amount,next_date,frequency_unit,frequency_value,is_active)"
    " VALUES (1,1,'Salary',2000.00,'2026-08-01','months',1,1)",
    "INSERT INTO allocation_rule (id,income_source_id,bucket_id,amount)"
    " VALUES (1,1,3,200.00),(2,1,4,NULL)",
    "INSERT INTO `transaction` (id,user_id,bucket_id,amount,note,timestamp)"
    " VALUES (1,1,3,-12.34,'Coffee','2026-08-01 10:00:00')",
]


def run(cmd):
    env = dict(os.environ, FLASK_APP="app.py", DB_URI=DB_URI,
               SECRET_KEY="test-only", COOKIE_SECURE="false")
    r = subprocess.run(cmd, cwd=APP_DIR, env=env, shell=True,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FAILED: {cmd}\n{r.stdout}\n{r.stderr}")
        sys.exit(1)
    return r.stdout + r.stderr


engine = sa.create_engine(DB_URI)

print("== building PRE-change schema with data (simulating production) ==")
with engine.begin() as c:
    for t in ['transaction', 'allocation_rule', 'income_source', 'bucket', 'user', 'alembic_version']:
        c.execute(sa.text(f"DROP TABLE IF EXISTS `{t}`"))
    for stmt in OLD_SCHEMA + SEED:
        c.execute(sa.text(stmt))

with engine.connect() as c:
    before = c.execute(sa.text(
        "SELECT id, balance FROM bucket ORDER BY id")).all()
print("   before:", before)

print("\n== step 1: flask db stamp 0001_baseline ==")
print("  ", run(f"{FLASK} db stamp 0001_baseline").strip().splitlines()[-1:])

print("\n== step 2: flask db upgrade ==")
out = run(f"{FLASK} db upgrade")
print("  ", [l for l in out.splitlines() if 'Running upgrade' in l])

print("\n== verifying resulting schema ==")
with engine.connect() as c:
    cols = c.execute(sa.text("""
        SELECT table_name, column_name, column_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND column_name IN ('balance','target_amount','amount')
        ORDER BY table_name, column_name""")).all()
    for row in cols:
        print("  ", row)

    after = c.execute(sa.text("SELECT id, balance FROM bucket ORDER BY id")).all()
    print("   after:", after)
    rules = c.execute(sa.text("SELECT id, amount FROM allocation_rule ORDER BY id")).all()
    print("   rules:", rules)

errors = []
for _, _, ctype, _ in cols:
    if 'decimal(10,2)' not in ctype.lower():
        errors.append(f"column not converted: {ctype}")
# NULLs must have become 0.00, other values preserved exactly
expected = {1: Decimal("1234.56"), 2: Decimal("80.10"), 3: Decimal("0.00"), 4: Decimal("150.00")}
for bid, bal in after:
    if bal != expected[bid]:
        errors.append(f"bucket {bid}: expected {expected[bid]}, got {bal}")
if dict(rules)[2] != Decimal("0.00"):
    errors.append(f"rule 2 NULL not backfilled: {dict(rules)[2]}")

print("\n== downgrade round-trip ==")
run(f"{FLASK} db downgrade 0001_baseline")
with engine.connect() as c:
    t = c.execute(sa.text("""SELECT column_type FROM information_schema.columns
        WHERE table_schema=DATABASE() AND table_name='bucket' AND column_name='balance'""")).scalar()
print("   bucket.balance after downgrade:", t)
run(f"{FLASK} db upgrade")

print("\n" + ("FAILURES:\n" + "\n".join(errors) if errors else "ALL MIGRATION CHECKS PASSED"))
sys.exit(1 if errors else 0)
