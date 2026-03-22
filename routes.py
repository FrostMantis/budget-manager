from flask import Blueprint, render_template, request, redirect, url_for, flash
from models import db, Bucket, Transaction, IncomeSource, AllocationRule
from services import FinanceService
from datetime import date

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    FinanceService.check_recurring_income()
    buckets = Bucket.query.filter_by(is_archived=False).all()
    return render_template('index.html', buckets=buckets)

@bp.route('/spend', methods=['POST'])
def spend():
    bucket_id = int(request.form.get('bucket_id'))
    amount = float(request.form.get('amount', 0))
    note = request.form.get('note', 'Expense')
    FinanceService.log_spend(bucket_id, amount, note)
    return redirect(url_for('main.index'))

@bp.route('/transfer', methods=['POST'])
def transfer():
    from_id = int(request.form.get('from_id'))
    to_id = int(request.form.get('to_id'))
    amount = float(request.form.get('amount', 0))
    note = request.form.get('note', 'Manual Transfer')
    
    if from_id == to_id:
        flash("Cannot transfer to the same bucket.")
    elif FinanceService.transfer_money(from_id, to_id, amount, note):
        flash("Transfer successful.")
    else:
        flash("Insufficient funds in source bucket.")
    return redirect(url_for('main.index'))

@bp.route('/income')
def income_view():
    sources = IncomeSource.query.filter_by(is_active=True).all()
    buckets = Bucket.query.filter_by(is_archived=False).all()
    return render_template('income.html', sources=sources, buckets=buckets)

@bp.route('/create-income-source', methods=['POST'])
def create_income_source():
    name = request.form.get('name')
    amount = float(request.form.get('amount', 0))
    unit = request.form.get('unit')
    start_date_str = request.form.get('start_date')
    
    start_date = date.fromisoformat(start_date_str) if start_date_str else None
    if unit != 'one-off' and not start_date:
        start_date = date.today()

    new_source = IncomeSource(name=name, amount=amount, frequency_unit=unit, next_date=start_date, is_active=True)
    db.session.add(new_source)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/edit-income-source/<int:id>', methods=['POST'])
def edit_income_source(id):
    source = IncomeSource.query.get_or_404(id)
    source.name = request.form.get('name')
    source.amount = float(request.form.get('amount', 0))
    source.frequency_unit = request.form.get('unit')
    next_date_str = request.form.get('next_date')
    if next_date_str:
        source.next_date = date.fromisoformat(next_date_str)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/add-rule/<int:source_id>', methods=['POST'])
def add_rule(source_id):
    bucket_id = int(request.form.get('bucket_id'))
    amount = float(request.form.get('amount', 0))
    new_rule = AllocationRule(income_source_id=source_id, bucket_id=bucket_id, amount=amount)
    db.session.add(new_rule)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/process-now/<int:source_id>')
def process_now(source_id):
    FinanceService.process_income_source(source_id)
    return redirect(url_for('main.index'))

@bp.route('/delete-source/<int:id>')
def delete_source(id):
    source = IncomeSource.query.get_or_404(id)
    db.session.delete(source)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/delete-rule/<int:id>')
def delete_rule(id):
    rule = AllocationRule.query.get_or_404(id)
    db.session.delete(rule)
    db.session.commit()
    return redirect(url_for('main.income_view'))

@bp.route('/manage')
def manage_view():
    buckets = Bucket.query.all()
    return render_template('manage.html', buckets=buckets)

@bp.route('/update-balance/<int:id>', methods=['POST'])
def update_balance(id):
    bucket = Bucket.query.get_or_404(id)
    new_balance = float(request.form.get('balance', 0))
    diff = new_balance - bucket.balance
    bucket.balance = new_balance
    db.session.add(Transaction(bucket_id=bucket.id, amount=diff, note="Manual Adjustment"))
    db.session.commit()
    return redirect(request.referrer)

@bp.route('/create-bucket', methods=['POST'])
def create_bucket():
    name = request.form.get('name')
    b_type = request.form.get('type')
    target = request.form.get('target')
    new_bucket = Bucket(name=name, bucket_type=b_type, target_amount=float(target) if target else None)
    db.session.add(new_bucket)
    db.session.commit()
    return redirect(request.referrer)

@bp.route('/delete-bucket/<int:id>')
def delete_bucket(id):
    bucket = Bucket.query.get_or_404(id)
    if bucket.bucket_type not in ['savings', 'everything']:
        db.session.delete(bucket)
        db.session.commit()
    return redirect(request.referrer)

@bp.route('/goals')
def goals_view():
    goals = Bucket.query.filter_by(bucket_type='goal', is_archived=False).all()
    return render_template('goals.html', goals=goals)

@bp.route('/archive-goal/<int:goal_id>', methods=['POST'])
def archive_goal(goal_id):
    cost = float(request.form.get('actual_cost', 0))
    FinanceService.finalize_goal(goal_id, cost)
    return redirect(url_for('main.goals_view'))

@bp.route('/history')
def history():
    transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    return render_template('history.html', transactions=transactions)

@bp.route('/delete-transaction/<int:id>')
def delete_transaction(id):
    tx = Transaction.query.get_or_404(id)
    db.session.delete(tx)
    db.session.commit()
    return redirect(url_for('main.history'))