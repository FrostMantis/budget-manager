from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from models import db, User, Bucket, Transaction, IncomeSource, AllocationRule
from services import FinanceService
from datetime import date

bp = Blueprint('main', __name__)

# --- AUTH ROUTES ---

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('main.index'))
    return render_template('login.html')

@bp.route('/logout')
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
    bucket_id = int(request.form.get('bucket_id'))
    amount = float(request.form.get('amount', 0))
    note = request.form.get('note', 'Expense')
    # Verification: Ensure bucket belongs to user
    bucket = Bucket.query.filter_by(id=bucket_id, user_id=current_user.id).first_or_404()
    FinanceService.log_spend(current_user.id, bucket.id, amount, note)
    return redirect(url_for('main.index'))

@bp.route('/transfer', methods=['POST'])
@login_required
def transfer():
    from_id = int(request.form.get('from_id'))
    to_id = int(request.form.get('to_id'))
    amount = float(request.form.get('amount', 0))
    note = request.form.get('note', 'Manual Transfer')
    
    if from_id == to_id:
        flash("Cannot transfer to the same bucket.")
        return redirect(url_for('main.index'))
        
    source = Bucket.query.filter_by(id=from_id, user_id=current_user.id).first_or_404()
    dest = Bucket.query.filter_by(id=to_id, user_id=current_user.id).first_or_404()
    
    # This will now process even if source.balance < amount
    FinanceService.transfer_money(current_user.id, source.id, dest.id, amount, note)
    flash("Transfer processed.") 
    
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
    name = request.form.get('name')
    amount = float(request.form.get('amount', 0))
    unit = request.form.get('unit')
    start_date_str = request.form.get('start_date')
    
    start_date = date.fromisoformat(start_date_str) if start_date_str else date.today()

    new_source = IncomeSource(
        user_id=current_user.id,
        name=name,
        amount=amount,
        frequency_unit=unit,
        next_date=start_date,
        is_active=True
    )
    db.session.add(new_source)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/edit-income-source/<int:id>', methods=['POST'])
@login_required
def edit_income_source(id):
    source = IncomeSource.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    source.name = request.form.get('name')
    source.amount = float(request.form.get('amount', 0))
    source.frequency_unit = request.form.get('unit')
    next_date_str = request.form.get('next_date')
    if next_date_str:
        source.next_date = date.fromisoformat(next_date_str)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/add-rule/<int:source_id>', methods=['POST'])
@login_required
def add_rule(source_id):
    source = IncomeSource.query.filter_by(id=source_id, user_id=current_user.id).first_or_404()
    bucket_id = int(request.form.get('bucket_id'))
    amount = float(request.form.get('amount', 0))
    
    # Ensure destination bucket belongs to user
    Bucket.query.filter_by(id=bucket_id, user_id=current_user.id).first_or_404()
    
    new_rule = AllocationRule(income_source_id=source.id, bucket_id=bucket_id, amount=amount)
    db.session.add(new_rule)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/process-now/<int:source_id>')
@login_required
def process_now(source_id):
    source = IncomeSource.query.filter_by(id=source_id, user_id=current_user.id).first_or_404()
    FinanceService.process_income_source(current_user.id, source.id)
    return redirect(url_for('main.index'))

@bp.route('/delete-source/<int:id>')
@login_required
def delete_source(id):
    source = IncomeSource.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(source)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/delete-rule/<int:id>')
@login_required
def delete_rule(id):
    rule = AllocationRule.query.get_or_404(id)
    # Check parent source ownership
    source = IncomeSource.query.filter_by(id=rule.income_source_id, user_id=current_user.id).first_or_404()
    db.session.delete(rule)
    db.session.commit()
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
    new_balance = float(request.form.get('balance', 0))
    diff = new_balance - bucket.balance
    bucket.balance = new_balance
    db.session.add(Transaction(user_id=current_user.id, bucket_id=bucket.id, amount=diff, note="Manual Adjustment"))
    db.session.commit()
    return redirect(request.referrer)

@bp.route('/create-bucket', methods=['POST'])
@login_required
def create_bucket():
    name = request.form.get('name')
    b_type = request.form.get('type')
    target = request.form.get('target')
    new_bucket = Bucket(
        user_id=current_user.id,
        name=name,
        bucket_type=b_type,
        target_amount=float(target) if target else None
    )
    db.session.add(new_bucket)
    db.session.commit()
    return redirect(request.referrer)

@bp.route('/delete-bucket/<int:id>')
@login_required
def delete_bucket(id):
    bucket = Bucket.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    if bucket.bucket_type not in ['savings', 'everything']:
        db.session.delete(bucket)
        db.session.commit()
    return redirect(request.referrer)

# --- GOALS ---

@bp.route('/goals')
@login_required
def goals_view():
    goals = Bucket.query.filter_by(user_id=current_user.id, bucket_type='goal', is_archived=False).all()
    return render_template('goals.html', goals=goals)

@bp.route('/archive-goal/<int:goal_id>', methods=['POST'])
@login_required
def archive_goal(goal_id):
    goal = Bucket.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    cost = float(request.form.get('actual_cost', 0))
    FinanceService.finalize_goal(current_user.id, goal.id, cost)
    return redirect(url_for('main.goals_view'))

# --- HISTORY ---

@bp.route('/history')
@login_required
def history():
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.timestamp.desc()).all()
    return render_template('history.html', transactions=transactions)

@bp.route('/delete-transaction/<int:id>')
@login_required
def delete_transaction(id):
    tx = Transaction.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    db.session.delete(tx)
    db.session.commit()
    return redirect(url_for('main.history'))