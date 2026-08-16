# Deploying this change to production

Production is an existing database with real data. It has never been managed by
Alembic, so the first deploy has an extra one-time step: telling Alembic that
the current schema is revision `0001_baseline`.

**Do the one-time steps once. After that, deploys are just steps 5, 7 and 8.**

---

## What is in this change

Two categories:

- **Code-only** (CSRF, POST-only deletes, input validation, bug fixes). These
  need a restart and a `pip install`, nothing else.
- **One schema change** (`0002_money_numeric`): the five money columns go from
  `FLOAT` to `DECIMAL(10,2)`, and `bucket.balance` / `allocation_rule.amount`
  become `NOT NULL` (existing NULLs are backfilled to `0` by the migration).

---

## Before you start

### 1. Take a database dump. Non-negotiable.

The `FLOAT -> DECIMAL(10,2)` conversion rounds to two decimals. A balance
stored as `10.999999999` becomes `11.00`. That is the point of the change, but
it means `downgrade` restores the *column type*, not the lost precision.

```bash
mysqldump -u <user> -p <dbname> > ~/budget-backup-$(date +%F-%H%M).sql
```

### 2. Check for values that will not fit

`DECIMAL(10,2)` holds up to `99,999,999.99`. Anything larger errors out mid-migration.

```sql
SELECT 'bucket.balance' AS col, id, balance AS v FROM bucket WHERE ABS(balance) > 99999999.99
UNION ALL SELECT 'bucket.target', id, target_amount FROM bucket WHERE ABS(target_amount) > 99999999.99
UNION ALL SELECT 'income.amount', id, amount FROM income_source WHERE ABS(amount) > 99999999.99
UNION ALL SELECT 'rule.amount', id, amount FROM allocation_rule WHERE ABS(amount) > 99999999.99
UNION ALL SELECT 'tx.amount', id, amount FROM `transaction` WHERE ABS(amount) > 99999999.99;
```

Zero rows is what you want. If not, fix those rows first or widen the precision
in `migrations/versions/0002_money_numeric.py` **and** `MONEY` in `models.py`.

### 3. Check for overdue income sources — behaviour change, read this

Catch-up is not new — the old code already paid out overdue income. It just did
**one period per dashboard load** (a single `relativedelta(weeks=1)`, no loop).
The new code catches up all missed periods in one pass.

Whether that matters to you depends entirely on how often you open the app:

- **You load the dashboard more often than you get paid** (weekly income,
  near-daily visits): the old code kept up fine, your backlog is ~0, and the
  query below returns nothing interesting. Nothing changes.
- **You load it less often than you get paid**: the old code fell *permanently*
  behind and never recovered. Weekly income opened monthly credits one week per
  visit while four weeks accrue — roughly 12 weeks credited per 52 owed, with
  the gap widening every month.

So the risk is not "extra money appears". It is the opposite: money you were
always owed, which the old code was never going to deliver, all arrives on the
first dashboard load after deploy. Check how big that backlog is first:

```sql
SELECT id, name, amount, next_date, frequency_unit,
       DATEDIFF(CURDATE(), next_date) AS days_overdue
FROM income_source
WHERE is_active = 1 AND frequency_unit <> 'one-off'
  AND next_date IS NOT NULL AND next_date <= CURDATE();
```

Multiply `days_overdue` by the frequency to see how many payments will post at
once — e.g. 90 days overdue on a weekly source is ~13 payouts of `amount`.

- **No rows** — nothing to do.
- **A few periods behind** — genuinely money you should have been allocated.
  Let it run.
- **Badly stale** (an old source you stopped caring about, or a backlog you do
  not actually want credited): set `is_active = 0`, or roll `next_date` forward
  to the correct next payday *before* restarting —
  `UPDATE income_source SET next_date = '2026-09-01' WHERE id = <id>;`

If a backlog does post and you want it gone, the balances are the thing to fix
(History is a log; deleting entries there does not change balances). Correct the
bucket totals on the Wallets page, which writes a matching "Manual Adjustment"
ledger entry.

### 4. Add the new setting to `.env` on the server

```ini
COOKIE_SECURE=false
```

> **Read this before setting it to `true`.** The app serves plain HTTP on port
> 80. `SESSION_COOKIE_SECURE=true` makes the browser refuse to send the session
> cookie over HTTP, which locks out every user including you. Leave it `false`
> until the app is actually behind HTTPS/TLS, then flip it.

Also confirm `SECRET_KEY` is set — the app now refuses to boot without it,
because it signs both session cookies and CSRF tokens. **Do not change its
value**: changing it invalidates every existing session and logs everyone out.

---

## Deploy

### 5. Pull and install

```bash
cd /path/to/budget-manager
git pull
source venv/bin/activate
pip install -r requirements.txt      # adds Flask-WTF, Flask-Migrate, Alembic
```

### 6. One-time: mark the existing schema as the baseline

This writes a single row to a new `alembic_version` table. It does **not**
touch any of your data or tables.

```bash
export FLASK_APP=app.py
flask db stamp 0001_baseline
```

Verify:

```bash
flask db current      # should print: 0001_baseline
```

> If you skip this, `flask db upgrade` will try to run `0001_baseline` and fail
> with "table 'user' already exists". That failure is safe — just run the stamp
> and continue.

### 7. Apply the migration

```bash
flask db upgrade
```

Expected output ends with:

```
Running upgrade 0001_baseline -> 0002_money_numeric, Money columns: Float -> Numeric(10, 2).
```

### 8. Restart the service

```bash
sudo systemctl restart <your-service-name>
```

### 9. Verify

```bash
flask db current      # 0002_money_numeric (head)
```

```sql
SELECT column_name, column_type, is_nullable FROM information_schema.columns
WHERE table_schema = DATABASE() AND column_name IN ('balance','target_amount','amount');
-- every row should read decimal(10,2)
```

Then in a browser: log in, load the dashboard, log one small spend, check it
appears in History, and delete it. Confirm Logout works — **it is now a button,
not a link**, because it changes state.

---

## Rolling back

**Code-only problem** (something broken in a route or template):

```bash
git revert <merge-or-commit>      # or: git checkout <old-sha>
sudo systemctl restart <your-service-name>
```
The old code reads `DECIMAL` columns fine — SQLAlchemy's `Float` type happily
loads a decimal column. You can leave the schema migrated.

**Schema problem:**

```bash
flask db downgrade 0001_baseline
```
This restores `FLOAT` columns. Values already rounded to 2 decimals stay
rounded — restore the dump from step 1 if you need the original precision.

**Total rollback:**

```bash
mysql -u <user> -p <dbname> < ~/budget-backup-<timestamp>.sql
```

---

## Creating users

There is still no self-service registration. Users are created from the CLI,
which also creates the two system buckets (`savings` + `everything`) that the
service layer assumes exist:

```bash
flask create-user alice
# prompts for password twice
```

---

## Running the tests

`tests/` needs a **throwaway** MySQL/MariaDB — `test_migration.py` drops and
recreates every table. **Never point it at production.**

```bash
podman run -d --name bmtest -e MARIADB_ROOT_PASSWORD=test \
    -e MARIADB_DATABASE=budget -p 13306:3306 docker.io/library/mariadb:11

export DB_URI="mysql+pymysql://root:test@127.0.0.1:13306/budget"
export SECRET_KEY=test-only COOKIE_SECURE=false FLASK_BIN="$(which flask)"

python tests/test_migration.py    # prod upgrade path on seeded old-schema data
python tests/test_app.py          # CSRF, ownership, the bug fixes
python tests/test_render.py       # every page renders
```

---

## Future schema changes

Now that Alembic is wired in, the loop is:

```bash
# 1. edit models.py
flask db migrate -m "what changed"     # generates a revision
# 2. READ the generated file in migrations/versions/ before trusting it
flask db upgrade                        # apply locally
# 3. commit the migration file alongside the model change
```

On the server it is only ever `git pull && pip install -r requirements.txt &&
flask db upgrade && systemctl restart <service>`.
