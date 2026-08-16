from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from models import (
    db, User, Bucket, Transaction, IncomeSource, AllocationRule,
    SYSTEM_BUCKET_TYPES, FREQUENCY_UNITS,
)
from services import FinanceService
from forms import (
    InputError, flash_error, parse_amount, parse_id, parse_name, parse_choice,
)
from datetime import date

bp = Blueprint('main', __name__)

# Types a user is allowed to create. 'savings' and 'everything' are excluded:
# the service layer looks each up with .first() and assumes exactly one exists,
# so letting a crafted POST mint a second one would silently divert income.
CREATABLE_BUCKET_TYPES = ('standard', 'goal')


def parse_date(raw, field="Date"):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise InputError(f"{field} is invalid.")


# --- AUTH ROUTES ---

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('main.index'))
        # Previously failed logins re-rendered the form with no explanation.
        flash("Incorrect username or password.", "danger")
    return render_template('login.html')


@bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))


# --- DASHBOARD & SPENDING ---

@bp.route('/')
@login_required
def index():
    FinanceService.check_recurring_income(current_user.id)
    buckets = Bucket.query.filter_by(user_id=current_user.id, is_archived=False).all()
    return render_template('index.html', buckets=buckets)


@bp.route('/spend', methods=['POST'])
@login_required
def spend():
    try:
        bucket_id = parse_id(request.form.get('bucket_id'), "Wallet")
        amount = parse_amount(request.form.get('amount'), "Amount")
    except InputError as err:
        flash_error(err)
        return redirect(url_for('main.index'))

    note = (request.form.get('note') or '').strip() or 'Expense'
    # Verification: Ensure bucket belongs to user
    bucket = Bucket.query.filter_by(id=bucket_id, user_id=current_user.id).first_or_404()
    FinanceService.log_spend(current_user.id, bucket.id, amount, note)
    flash(f"Logged {amount}€ from {bucket.name}.", "success")
    return redirect(url_for('main.index'))


@bp.route('/transfer', methods=['POST'])
@login_required
def transfer():
    try:
        from_id = parse_id(request.form.get('from_id'), "Source")
        to_id = parse_id(request.form.get('to_id'), "Destination")
        amount = parse_amount(request.form.get('amount'), "Amount")
    except InputError as err:
        flash_error(err)
        return redirect(url_for('main.index'))

    note = (request.form.get('note') or '').strip() or 'Manual Transfer'

    if from_id == to_id:
        flash("Cannot transfer to the same bucket.", "danger")
        return redirect(url_for('main.index'))

    source = Bucket.query.filter_by(id=from_id, user_id=current_user.id).first_or_404()
    dest = Bucket.query.filter_by(id=to_id, user_id=current_user.id).first_or_404()

    # This will process even if source.balance < amount
    FinanceService.transfer_money(current_user.id, source.id, dest.id, amount, note)
    flash(f"Transferred {amount}€ from {source.name} to {dest.name}.", "success")

    return redirect(url_for('main.index'))


# --- INCOME & RULES ---

@bp.route('/income')
@login_required
def income_view():
    sources = IncomeSource.query.filter_by(user_id=current_user.id, is_active=True).all()
    buckets = Bucket.query.filter_by(user_id=current_user.id, is_archived=False).all()
    return render_template('income.html', sources=sources, buckets=buckets)


@bp.route('/create-income-source', methods=['POST'])
@login_required
def create_income_source():
    try:
        name = parse_name(request.form.get('name'), "Source name")
        amount = parse_amount(request.form.get('amount'), "Amount")
        unit = parse_choice(request.form.get('unit'), FREQUENCY_UNITS, "Frequency")
        start_date = parse_date(request.form.get('start_date'), "Start date") or date.today()
    except InputError as err:
        flash_error(err)
        return redirect(url_for('main.income_view'))

    db.session.add(IncomeSource(
        user_id=current_user.id,
        name=name,
        amount=amount,
        frequency_unit=unit,
        next_date=start_date,
        is_active=True,
    ))
    db.session.commit()
    flash(f"Added income source {name}.", "success")
    return redirect(url_for('main.income_view'))


@bp.route('/edit-income-source/<int:id>', methods=['POST'])
@login_required
def edit_income_source(id):
    source = IncomeSource.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    try:
        source.name = parse_name(request.form.get('name'), "Source name")
        source.amount = parse_amount(request.form.get('amount'), "Amount")
        source.frequency_unit = parse_choice(
            request.form.get('unit'), FREQUENCY_UNITS, "Frequency")
        next_date = parse_date(request.form.get('next_date'), "Next date")
    except InputError as err:
        db.session.rollback()
        flash_error(err)
        return redirect(url_for('main.income_view'))

    if next_date:
        source.next_date = next_date
    # A recurring source with no next_date pays out once and deactivates, so
    # make sure switching one-off -> recurring always leaves a date behind.
    if source.frequency_unit != 'one-off' and not source.next_date:
        source.next_date = date.today()

    db.session.commit()
    flash(f"Updated {source.name}.", "success")
    return redirect(url_for('main.income_view'))


@bp.route('/add-rule/<int:source_id>', methods=['POST'])
@login_required
def add_rule(source_id):
    source = IncomeSource.query.filter_by(id=source_id, user_id=current_user.id).first_or_404()
    try:
        bucket_id = parse_id(request.form.get('bucket_id'), "Wallet")
        amount = parse_amount(request.form.get('amount'), "Rule amount")
    except InputError as err:
        flash_error(err)
        return redirect(url_for('main.income_view'))

    # Ensure destination bucket belongs to user
    bucket = Bucket.query.filter_by(id=bucket_id, user_id=current_user.id).first_or_404()

    db.session.add(AllocationRule(
        income_source_id=source.id, bucket_id=bucket.id, amount=amount))
    db.session.commit()
    flash(f"Added rule: {amount}€ to {bucket.name}.", "success")
    return redirect(url_for('main.income_view'))


@bp.route('/process-now/<int:source_id>', methods=['POST'])
@login_required
def process_now(source_id):
    source = IncomeSource.query.filter_by(id=source_id, user_id=current_user.id).first_or_404()
    name = source.name
    FinanceService.process_income_source(current_user.id, source.id)
    flash(f"Processed {name}.", "success")
    return redirect(url_for('main.index'))


@bp.route('/delete-source/<int:id>', methods=['POST'])
@login_required
def delete_source(id):
    source = IncomeSource.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    name = source.name
    db.session.delete(source)
    db.session.commit()
    flash(f"Deleted income source {name}.", "success")
    return redirect(url_for('main.income_view'))


@bp.route('/delete-rule/<int:id>', methods=['POST'])
@login_required
def delete_rule(id):
    rule = db.session.get(AllocationRule, id)
    if rule is None:
        flash("Rule not found.", "danger")
        return redirect(url_for('main.income_view'))
    # Check parent source ownership
    IncomeSource.query.filter_by(
        id=rule.income_source_id, user_id=current_user.id).first_or_404()
    db.session.delete(rule)
    db.session.commit()
    flash("Deleted allocation rule.", "success")
    return redirect(url_for('main.income_view'))


# --- BUCKET MANAGEMENT ---

@bp.route('/manage')
@login_required
def manage_view():
    buckets = Bucket.query.filter_by(user_id=current_user.id).all()
    return render_template('manage.html', buckets=buckets)


@bp.route('/update-balance/<int:id>', methods=['POST'])
@login_required
def update_balance(id):
    bucket = Bucket.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    # 'next' carries the page to return to. Previously this used
    # request.referrer, which is attacker-controlled (open redirect) and 500s
    # when the header is absent.
    dest = safe_next(request.form.get('next'), 'main.manage_view')

    try:
        # A manual correction may legitimately be zero or negative.
        new_balance = parse_amount(
            request.form.get('balance'), "Balance",
            allow_zero=True, allow_negative=True)
    except InputError as err:
        flash_error(err)
        return redirect(dest)

    diff = new_balance - Decimal(bucket.balance or 0)
    bucket.balance = new_balance
    if diff != 0:
        db.session.add(Transaction(
            user_id=current_user.id, bucket_id=bucket.id, amount=diff,
            note="Manual Adjustment"))
    db.session.commit()
    flash(f"Set {bucket.name} to {new_balance}€.", "success")
    return redirect(dest)


@bp.route('/create-bucket', methods=['POST'])
@login_required
def create_bucket():
    dest = safe_next(request.form.get('next'), 'main.manage_view')
    try:
        name = parse_name(request.form.get('name'), "Wallet name")
        b_type = parse_choice(
            request.form.get('type'), CREATABLE_BUCKET_TYPES, "Wallet type")
        # A goal must have a target (the progress bar divides by it); a
        # standard wallet may optionally carry one.
        target = None
        if b_type == 'goal' or request.form.get('target'):
            target = parse_amount(request.form.get('target'), "Target amount")
    except InputError as err:
        flash_error(err)
        return redirect(dest)

    db.session.add(Bucket(
        user_id=current_user.id,
        name=name,
        bucket_type=b_type,
        target_amount=target,
    ))
    db.session.commit()
    flash(f"Created {name}.", "success")
    return redirect(dest)


@bp.route('/delete-bucket/<int:id>', methods=['POST'])
@login_required
def delete_bucket(id):
    bucket = Bucket.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    dest = safe_next(request.form.get('next'), 'main.manage_view')

    if bucket.bucket_type in SYSTEM_BUCKET_TYPES:
        flash(f"{bucket.name} is a system bucket and cannot be deleted.", "danger")
        return redirect(dest)

    name = bucket.name
    # Ledger entries are kept: Transaction.bucket_id is nullable and is set to
    # NULL here, so history survives. Allocation rules cascade away.
    Transaction.query.filter_by(
        user_id=current_user.id, bucket_id=bucket.id).update({'bucket_id': None})
    db.session.delete(bucket)
    db.session.commit()
    flash(f"Deleted {name}.", "success")
    return redirect(dest)


# --- GOALS ---

@bp.route('/goals')
@login_required
def goals_view():
    goals = Bucket.query.filter_by(
        user_id=current_user.id, bucket_type='goal', is_archived=False).all()
    return render_template('goals.html', goals=goals)


@bp.route('/archive-goal/<int:goal_id>', methods=['POST'])
@login_required
def archive_goal(goal_id):
    goal = Bucket.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    try:
        cost = parse_amount(request.form.get('actual_cost'), "Actual cost",
                            allow_zero=True)
    except InputError as err:
        flash_error(err)
        return redirect(url_for('main.goals_view'))

    name = goal.name
    FinanceService.finalize_goal(current_user.id, goal.id, cost)
    flash(f"Completed goal {name}.", "success")
    return redirect(url_for('main.goals_view'))


# --- HISTORY ---

@bp.route('/history')
@login_required
def history():
    transactions = Transaction.query.filter_by(
        user_id=current_user.id).order_by(Transaction.timestamp.desc()).all()
    return render_template('history.html', transactions=transactions)


@bp.route('/delete-transaction/<int:id>', methods=['POST'])
@login_required
def delete_transaction(id):
    tx = Transaction.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(tx)
    db.session.commit()
    flash("Deleted log entry. Balances were not changed.", "success")
    return redirect(url_for('main.history'))


def safe_next(raw, fallback_endpoint):
    """Resolve a 'next' form value to a local path only.

    Anything absolute, protocol-relative, or otherwise off-site falls back, so
    this cannot be used as an open redirect.
    """
    if raw and raw.startswith('/') and not raw.startswith('//'):
        return raw
    return url_for(fallback_endpoint)
