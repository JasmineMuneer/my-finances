# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, jsonify, make_response, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import init_db, get_db_connection, get_setting, set_setting
from datetime import datetime, timedelta
import psycopg2
import io
import csv as csv_module
import os
import secrets
import json
import urllib.request
import urllib.error
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from decimal import Decimal
from flask.json.provider import DefaultJSONProvider

class _SafeJSONProvider(DefaultJSONProvider):
    """Extend Flask's JSON serializer to handle Decimal and date types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, 'isoformat'):   # date / datetime
            return obj.isoformat()
        return super().default(obj)

app = Flask(__name__)
app.json_provider_class = _SafeJSONProvider
app.json = _SafeJSONProvider(app)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'my-finances-super-secret-key-123'

# ── AI Financial Insights ───────────────────────────────────────────────────
# Get a free key at https://aistudio.google.com/
# Set as an environment variable OR paste directly between the quotes.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ── Email / Brevo SMTP configuration for password reset ─────────────────────
SMTP_HOST    = os.environ.get("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "2525"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
MAIL_FROM    = os.environ.get("MAIL_FROM", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").rstrip('/')

# Initialize DB on startup
init_db()

# ── Auth guards ─────────────────────────────────────────────────────────────

@app.before_request
def require_login():
    allowed_routes = ['login', 'signup', 'static', 'forgot_password', 'reset_password']
    if request.endpoint not in allowed_routes and 'user_id' not in session:
        return redirect(url_for('login'))

@app.after_request
def add_utf8_charset(response):
    """Ensure every HTML response is served as UTF-8 so ₹ renders correctly."""
    if response.content_type and response.content_type.startswith('text/html'):
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

# ── Auth routes ─────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = %s', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email    = request.form.get('email', '').strip().lower()
        conn = get_db_connection()
        existing = conn.execute('SELECT id FROM users WHERE username = %s', (username,)).fetchone()
        if existing:
            conn.close()
            flash('Username already exists')
            return redirect(url_for('signup'))
        hashed = generate_password_hash(password)
        cursor = conn.execute('INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id', (username, hashed, email))
        user_id = cursor.fetchone()['id']
        conn.execute('INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s)', (user_id, 'currency', '\u20b9'))
        default_expenses = ['Food', 'Groceries', 'Shopping', 'Transport', 'Housing', 'Utilities', 'Entertainment', 'Healthcare', 'Other']
        default_incomes  = ['Salary', 'Freelance', 'Investment', 'Other Income']
        for cat in default_expenses:
            conn.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, 'expense')", (user_id, cat))
        for cat in default_incomes:
            conn.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, 'income')", (user_id, cat))
        conn.commit()
        conn.close()
        session['user_id'] = user_id
        session['username'] = username
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Password Reset ───────────────────────────────────────────────────────────

def send_reset_email(to_email, reset_link):
    """Send a password reset email via Brevo SMTP."""
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("Brevo SMTP credentials (SMTP_USER / SMTP_PASS) are not configured")
    if not MAIL_FROM:
        raise RuntimeError("MAIL_FROM is not configured")

    text_body = f"""Hi,

You requested a password reset for your My Finances account.

Click the link below to reset your password (valid for 1 hour):
{reset_link}

If you did not request this, you can safely ignore this email.

\u2014 My Finances"""
    html_body = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;background:#FDFCFF;border-radius:16px;border:1px solid #e5d9f2;">
        <h2 style="color:#9B72AF;margin-bottom:8px;">Password Reset</h2>
        <p style="color:#555;font-size:15px;">You requested a password reset for your <strong>My Finances</strong> account.</p>
        <a href="{reset_link}" style="display:inline-block;margin:24px 0;padding:12px 28px;background:#FFAFCC;color:#fff;border-radius:12px;text-decoration:none;font-weight:600;font-size:15px;">
            Reset My Password
        </a>
        <p style="color:#aaa;font-size:12px;">This link expires in <strong>1 hour</strong>. If you did not request a reset, ignore this email.</p>
    </div>"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'My Finances \u2014 Password Reset Request'
    msg['From']    = f'My Finances <{MAIL_FROM}>'
    msg['To']      = to_email
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(MAIL_FROM, to_email, msg.as_string())

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    msg = None
    msg_type = 'info'
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE LOWER(email)=%s", (email,)).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            expires = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", (user['id'],))
            conn.execute("INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)", (user['id'], token, expires))
            conn.commit()
            conn.close()
            reset_link = f"{APP_BASE_URL}/reset-password/{token}"
            try:
                send_reset_email(email, reset_link)
                msg = "A password reset link has been sent to your email address. Please check your inbox."
                msg_type = 'success'
            except Exception as e:
                print(f"--- BREVO SMTP ERROR ---: {type(e).__name__}: {e}")
                # Fallback: show the link directly (useful when SMTP is not set up)
                msg = f"Email sending failed (check server logs). Use this link to reset your password: {reset_link}"
                msg_type = 'warning'
        else:
            conn.close()
            # Don't reveal whether the email exists — security best practice
            msg = "If that email is registered, a reset link has been sent."
            msg_type = 'success'
    return render_template('forgot_password.html', msg=msg, msg_type=msg_type)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_db_connection()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token=%s AND expires_at > %s", (token, now)
    ).fetchone()
    if not record:
        conn.close()
        return render_template('reset_password.html', invalid=True)
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if len(password) < 6:
            conn.close()
            return render_template('reset_password.html', token=token, invalid=False, error="Password must be at least 6 characters.")
        if password != confirm:
            conn.close()
            return render_template('reset_password.html', token=token, invalid=False, error="Passwords do not match.")
        hashed = generate_password_hash(password)
        conn.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, record['user_id']))
        conn.execute("DELETE FROM password_reset_tokens WHERE token=%s", (token,))
        conn.commit()
        conn.close()
        flash('Your password has been reset. Please log in.')
        return redirect(url_for('login'))
    conn.close()
    return render_template('reset_password.html', token=token, invalid=False)

# ── Context Processors ───────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    if 'user_id' in session:
        user_id = session['user_id']
        conn = get_db_connection()
        currency = get_setting(user_id, 'currency', '\u20b9')
        expense_cats = conn.execute("SELECT name FROM categories WHERE user_id=%s AND type='expense' ORDER BY name", (user_id,)).fetchall()
        income_cats  = conn.execute("SELECT name FROM categories WHERE user_id=%s AND type='income' ORDER BY name",  (user_id,)).fetchall()
        conn.close()
        return dict(
            currency=currency,
            expense_categories=[row['name'] for row in expense_cats],
            income_categories=[row['name'] for row in income_cats]
        )
    return dict(currency='\u20b9', expense_categories=[], income_categories=[])

# ── Helper ───────────────────────────────────────────────────────────────────

def get_current_month():
    return datetime.now().strftime('%Y-%m')

# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    conn = get_db_connection()
    current_month = get_current_month()
    user_id = session['user_id']
    income    = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses  = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    savings   = income - expenses
    savings_rate = (savings / income * 100) if income > 0 else 0
    recent_transactions = conn.execute("SELECT * FROM transactions WHERE user_id=%s ORDER BY date DESC, id DESC LIMIT 5", (user_id,)).fetchall()
    top_categories = conn.execute("""
        SELECT category, SUM(amount) as total FROM transactions
        WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s
        GROUP BY category ORDER BY total DESC LIMIT 3
    """, (user_id, current_month)).fetchall()
    goals = conn.execute("SELECT * FROM goals WHERE user_id=%s", (user_id,)).fetchall()
    today = datetime.now().day
    upcoming_bills = conn.execute("SELECT * FROM bills WHERE user_id=%s AND is_active=1 AND due_day>=%s ORDER BY due_day ASC LIMIT 3", (user_id, today)).fetchall()
    upcoming_emis  = conn.execute("SELECT * FROM loans WHERE user_id=%s AND remaining_installments>0 AND due_day>=%s ORDER BY due_day ASC LIMIT 3", (user_id, today)).fetchall()
    money_score = calculate_money_score(conn, user_id)
    conn.close()
    return render_template('dashboard.html',
        income=income, expenses=expenses, savings=savings, savings_rate=savings_rate,
        recent_transactions=recent_transactions, top_categories=top_categories,
        goals=goals, upcoming_bills=upcoming_bills, upcoming_emis=upcoming_emis,
        money_score=money_score, current_month=current_month)

def calculate_money_score(conn, user_id):
    """Compute the 0–1000 Money Score for the current month."""
    current_month = get_current_month()
    income   = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0

    # 1. Savings score (max 300)
    if income == 0:
        savings_score = 300
    else:
        savings_rate = max(0, (income - expenses) / income)
        savings_score = min(300, int(savings_rate * 1200))

    # 2. Budget score (max 250)
    budgets = conn.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    if not budgets:
        budget_score = 250
    else:
        budget_score = 250
        for b in budgets:
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, b['category'], current_month)).fetchone()['t'] or 0
            if b['amount'] > 0:
                if spent > b['amount']:
                    budget_score -= 60
                elif spent > b['amount'] * 0.9:
                    budget_score -= 20
        budget_score = max(0, budget_score)

    # 3. EMI score (max 200) — full score; deducted in future if overdue logic added
    emi_score = 200

    # 4. Goals score (max 250)
    goals = conn.execute("SELECT * FROM goals WHERE user_id=%s", (user_id,)).fetchall()
    if not goals:
        goals_score = 250
    else:
        valid_goals = [g for g in goals if g['target_amount'] > 0]
        if not valid_goals:
            goals_score = 250
        else:
            progress_avg = sum(min(1.0, g['current_amount'] / g['target_amount']) for g in valid_goals) / len(valid_goals)
            goals_score = int(progress_avg * 250)

    return min(1000, savings_score + budget_score + emi_score + goals_score)

# ── Transactions ─────────────────────────────────────────────────────────────

@app.route('/transactions', methods=['GET'])
def transactions():
    conn = get_db_connection()
    month_filter = request.args.get('month', get_current_month())
    type_filter  = request.args.get('type', 'all')
    q = request.args.get('q', '').strip()
    user_id = session['user_id']
    query  = "SELECT * FROM transactions WHERE user_id=%s AND substring(date from 1 for 7)=%s"
    params = [user_id, month_filter]
    if type_filter in ['income', 'expense']:
        query += " AND type=%s"
        params.append(type_filter)
    if q:
        query += " AND (description ILIKE %s OR notes ILIKE %s OR category ILIKE %s)"
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    query += " ORDER BY date DESC, id DESC"
    transactions_list = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('transactions.html', transactions=transactions_list,
                           selected_month=month_filter, selected_type=type_filter, q=q)

@app.route('/transactions/add', methods=['POST'])
def add_transaction():
    user_id        = session['user_id']
    amount         = float(request.form['amount'])
    txn_type       = request.form['type']
    category       = request.form['category']
    date           = request.form['date']
    payment_method = request.form.get('payment_method', '')
    description    = request.form.get('description', '')
    notes          = request.form.get('notes', '')
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO transactions (user_id, amount, type, category, date, payment_method, description, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (user_id, amount, txn_type, category, date, payment_method, description, notes))
    conn.commit()
    conn.close()
    return redirect(url_for('transactions'))

@app.route('/transactions/delete/<int:id>', methods=['POST'])
def delete_transaction(id):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute('DELETE FROM transactions WHERE id=%s AND user_id=%s', (id, user_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('transactions'))

@app.route('/transactions/edit/<int:id>', methods=['GET', 'POST'])
def edit_transaction(id):
    conn = get_db_connection()
    user_id = session['user_id']
    txn = conn.execute("SELECT * FROM transactions WHERE id=%s AND user_id=%s", (id, user_id)).fetchone()
    if not txn:
        conn.close()
        return redirect(url_for('transactions'))
    if request.method == 'POST':
        amount         = float(request.form['amount'])
        txn_type       = request.form['type']
        category       = request.form['category']
        date           = request.form['date']
        payment_method = request.form.get('payment_method', '')
        description    = request.form.get('description', '')
        notes          = request.form.get('notes', '')
        conn.execute('''
            UPDATE transactions
            SET amount=%s, type=%s, category=%s, date=%s, payment_method=%s, description=%s, notes=%s
            WHERE id=%s AND user_id=%s
        ''', (amount, txn_type, category, date, payment_method, description, notes, id, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for('transactions'))
    conn.close()
    return render_template('edit_transaction.html', txn=txn)

# ── Analytics ────────────────────────────────────────────────────────────────

@app.route('/analytics')
def analytics():
    return render_template('analytics.html')

@app.route('/api/analytics/data')
def analytics_data():
    conn = get_db_connection()
    current_month = request.args.get('month', get_current_month())
    user_id = session['user_id']
    expenses = conn.execute("SELECT category, SUM(amount) as total FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s GROUP BY category", (user_id, current_month)).fetchall()
    trend    = conn.execute("""
        SELECT substring(date from 1 for 7) as month, type, SUM(amount) as total
        FROM transactions WHERE user_id=%s AND date::date >= CURRENT_DATE - INTERVAL '6 months'
        GROUP BY month, type ORDER BY month ASC
    """, (user_id,)).fetchall()
    conn.close()
    return jsonify({
        'expenses_by_category': [{'category': r['category'], 'total': r['total']} for r in expenses],
        'trend': [{'month': r['month'], 'type': r['type'], 'total': r['total']} for r in trend]
    })

# ── Budgets ──────────────────────────────────────────────────────────────────

@app.route('/budgets', methods=['GET', 'POST'])
def budgets():
    conn = get_db_connection()
    current_month = get_current_month()
    user_id = session['user_id']
    if request.method == 'POST':
        category = request.form['category']
        amount   = float(request.form['amount'])
        existing = conn.execute("SELECT id FROM budgets WHERE user_id=%s AND category=%s AND month=%s", (user_id, category, current_month)).fetchone()
        if existing:
            conn.execute("UPDATE budgets SET amount=%s WHERE id=%s", (amount, existing['id']))
        else:
            conn.execute("INSERT INTO budgets (user_id, category, amount, month) VALUES (%s, %s, %s, %s)", (user_id, category, amount, current_month))
        conn.commit()
        conn.close()
        return redirect(url_for('budgets'))
    budgets_list = conn.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    budget_data = []
    for b in budgets_list:
        cat = b['category']
        if cat == 'Overall':
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
        else:
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, cat, current_month)).fetchone()['t'] or 0
        budget_data.append({
            'id': b['id'], 'category': cat, 'amount': b['amount'],
            'spent': spent, 'remaining': b['amount'] - spent,
            'percent': min((spent / b['amount']) * 100, 100) if b['amount'] > 0 else 0,
            'over': spent > b['amount']
        })
    conn.close()
    return render_template('budgets.html', budgets=budget_data)

@app.route('/budgets/delete/<int:id>', methods=['POST'])
def delete_budget(id):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("DELETE FROM budgets WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('budgets'))

# ── Goals ────────────────────────────────────────────────────────────────────

@app.route('/goals', methods=['GET', 'POST'])
def goals():
    conn = get_db_connection()
    user_id = session['user_id']
    if request.method == 'POST':
        name                 = request.form['name']
        target_amount        = float(request.form['target_amount'])
        target_date          = request.form.get('target_date', '')
        monthly_contribution = float(request.form.get('monthly_contribution', 0))
        conn.execute('''
            INSERT INTO goals (user_id, name, target_amount, current_amount, target_date, monthly_contribution)
            VALUES (%s, %s, %s, 0, %s, %s)
        ''', (user_id, name, target_amount, target_date, monthly_contribution))
        conn.commit()
        conn.close()
        return redirect(url_for('goals'))
    goals_list = conn.execute("SELECT * FROM goals WHERE user_id=%s ORDER BY id DESC", (user_id,)).fetchall()
    goals_data = []
    for g in goals_list:
        progress = (g['current_amount'] / g['target_amount'] * 100) if g['target_amount'] > 0 else 0
        goals_data.append({
            'id': g['id'], 'name': g['name'],
            'target_amount': g['target_amount'], 'current_amount': g['current_amount'],
            'progress': min(progress, 100), 'target_date': g['target_date'],
            'monthly_contribution': g['monthly_contribution']
        })
    conn.close()
    return render_template('goals.html', goals=goals_data)

@app.route('/goals/update/<int:id>', methods=['POST'])
def update_goal(id):
    added_amount = float(request.form['added_amount'])
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("UPDATE goals SET current_amount = current_amount + %s WHERE id=%s AND user_id=%s", (added_amount, id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('goals'))

@app.route('/goals/delete/<int:id>', methods=['POST'])
def delete_goal(id):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("DELETE FROM goals WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('goals'))

# ── Loans / EMIs ─────────────────────────────────────────────────────────────

@app.route('/loans', methods=['GET', 'POST'])
def loans():
    conn = get_db_connection()
    user_id = session['user_id']
    if request.method == 'POST':
        name               = request.form['name']
        lender             = request.form.get('lender', '')
        principal          = float(request.form['principal'])
        interest_rate      = float(request.form.get('interest_rate', 0))
        monthly_emi        = float(request.form['monthly_emi'])
        total_installments = int(request.form['total_installments'])
        due_day            = int(request.form.get('due_day', 1))
        conn.execute('''
            INSERT INTO loans (user_id, name, lender, principal, interest_rate, monthly_emi, total_installments, remaining_installments, due_day)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, name, lender, principal, interest_rate, monthly_emi, total_installments, total_installments, due_day))
        conn.commit()
        return redirect(url_for('loans'))
    loans_list = conn.execute("SELECT * FROM loans WHERE user_id=%s ORDER BY id DESC", (user_id,)).fetchall()
    total_outstanding = sum(
        l['principal'] * (l['remaining_installments'] / l['total_installments'])
        if l['total_installments'] > 0 else 0
        for l in loans_list
    )
    total_emi = sum(l['monthly_emi'] for l in loans_list if l['remaining_installments'] > 0)
    conn.close()
    return render_template('loans.html', loans=loans_list, total_outstanding=total_outstanding, total_emi=total_emi)

@app.route('/loans/pay/<int:id>', methods=['POST'])
def pay_emi(id):
    conn = get_db_connection()
    user_id = session['user_id']
    loan = conn.execute("SELECT * FROM loans WHERE id=%s AND user_id=%s", (id, user_id)).fetchone()
    if loan and loan['remaining_installments'] > 0:
        conn.execute('''
            INSERT INTO transactions (user_id, amount, type, category, date, description, notes)
            VALUES (%s, %s, 'expense', 'EMI', %s, %s, %s)
        ''', (user_id, loan['monthly_emi'], datetime.now().strftime('%Y-%m-%d'),
              f"EMI Payment: {loan['name']}", "Auto-generated from EMI Tracker"))
        conn.execute("UPDATE loans SET remaining_installments = remaining_installments - 1 WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('loans'))

@app.route('/loans/delete/<int:id>', methods=['POST'])
def delete_loan(id):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("DELETE FROM loans WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('loans'))

# ── Bills ────────────────────────────────────────────────────────────────────

@app.route('/bills', methods=['GET', 'POST'])
def bills():
    conn = get_db_connection()
    user_id = session['user_id']
    if request.method == 'POST':
        name      = request.form['name']
        amount    = float(request.form['amount'])
        frequency = request.form.get('frequency', 'monthly')
        due_day   = int(request.form.get('due_day', 1))
        category  = request.form.get('category', 'Utilities')
        conn.execute('''
            INSERT INTO bills (user_id, name, amount, frequency, due_day, category)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, name, amount, frequency, due_day, category))
        conn.commit()
        return redirect(url_for('bills'))
    bills_list   = conn.execute("SELECT * FROM bills WHERE user_id=%s ORDER BY due_day ASC", (user_id,)).fetchall()
    monthly_cost = sum(b['amount'] for b in bills_list if b['frequency'] == 'monthly' and b['is_active'])
    yearly_cost  = sum(b['amount'] for b in bills_list if b['frequency'] == 'yearly'  and b['is_active']) + (monthly_cost * 12)
    conn.close()
    return render_template('bills.html', bills=bills_list, monthly_cost=monthly_cost, yearly_cost=yearly_cost)

@app.route('/bills/toggle/<int:id>', methods=['POST'])
def toggle_bill(id):
    conn = get_db_connection()
    user_id = session['user_id']
    bill = conn.execute("SELECT is_active FROM bills WHERE id=%s AND user_id=%s", (id, user_id)).fetchone()
    if bill:
        conn.execute("UPDATE bills SET is_active=%s WHERE id=%s", (0 if bill['is_active'] else 1, id))
        conn.commit()
    conn.close()
    return redirect(url_for('bills'))

@app.route('/bills/pay/<int:id>', methods=['POST'])
def pay_bill(id):
    conn = get_db_connection()
    user_id = session['user_id']
    bill = conn.execute("SELECT * FROM bills WHERE id=%s AND user_id=%s", (id, user_id)).fetchone()
    if bill:
        conn.execute('''
            INSERT INTO transactions (user_id, amount, type, category, date, description, notes)
            VALUES (%s, %s, 'expense', %s, %s, %s, %s)
        ''', (user_id, bill['amount'], bill['category'], datetime.now().strftime('%Y-%m-%d'),
              f"Bill Payment: {bill['name']}", "Auto-generated from Bills Tracker"))
        conn.commit()
    conn.close()
    return redirect(url_for('bills'))

@app.route('/bills/delete/<int:id>', methods=['POST'])
def delete_bill(id):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("DELETE FROM bills WHERE id=%s AND user_id=%s", (id, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('bills'))

# ── Money Score ───────────────────────────────────────────────────────────────

@app.route('/score')
def score():
    conn = get_db_connection()
    current_month = get_current_month()
    user_id = session['user_id']

    income   = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0

    # Savings score (max 300)
    if income == 0:
        savings_score = 300
    else:
        savings_rate = max(0, (income - expenses) / income)
        savings_score = min(300, int(savings_rate * 1200))

    # Budget score (max 250)
    budgets_list = conn.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    if not budgets_list:
        budget_score = 250
    else:
        budget_score = 250
        for b in budgets_list:
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, b['category'], current_month)).fetchone()['t'] or 0
            if b['amount'] > 0:
                if spent > b['amount']:
                    budget_score -= 60
                elif spent > b['amount'] * 0.9:
                    budget_score -= 20
        budget_score = max(0, budget_score)

    # EMI score (max 200)
    emi_score = 200

    # Goals score (max 250)
    goals_list = conn.execute("SELECT * FROM goals WHERE user_id=%s", (user_id,)).fetchall()
    if not goals_list:
        goals_score = 250
    else:
        valid_goals = [g for g in goals_list if g['target_amount'] > 0]
        if not valid_goals:
            goals_score = 250
        else:
            progress_avg = sum(min(1.0, g['current_amount'] / g['target_amount']) for g in valid_goals) / len(valid_goals)
            goals_score = int(progress_avg * 250)

    total_score = min(1000, savings_score + budget_score + emi_score + goals_score)

    if total_score >= 950:
        insight = "Excellent! Your finances are in great shape. Keep up the consistent habits."
    elif total_score > 750:
        insight = "Your financial health is good. Small improvements to savings or budgets could push you higher."
    elif total_score > 500:
        insight = "You're on the right track. Focus on staying within budgets and building your savings goals."
    else:
        insight = "Focus on reducing overspending and building an emergency fund to improve your financial stability."

    conn.close()
    return render_template('score.html',
        score=total_score, savings_score=savings_score,
        budget_score=budget_score, emi_score=emi_score,
        goals_score=goals_score, insight=insight)

# ── Net Worth ─────────────────────────────────────────────────────────────────

@app.route('/net-worth', methods=['GET', 'POST'])
def net_worth():
    conn = get_db_connection()
    user_id = session['user_id']
    if request.method == 'POST':
        name          = request.form['name']
        item_type     = request.form['type']
        value         = float(request.form['value'])
        date_recorded = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("INSERT INTO assets_liabilities (user_id, name, type, value, date_recorded) VALUES (%s, %s, %s, %s, %s)",
                     (user_id, name, item_type, value, date_recorded))
        conn.commit()
        return redirect(url_for('net_worth'))
    items = conn.execute("SELECT * FROM assets_liabilities WHERE user_id=%s ORDER BY date_recorded DESC", (user_id,)).fetchall()
    latest_items = {}
    for item in items:
        if item['name'] not in latest_items:
            latest_items[item['name']] = item
    assets      = [i for i in latest_items.values() if i['type'] == 'asset']
    liabilities = [i for i in latest_items.values() if i['type'] == 'liability']
    total_assets      = sum(i['value'] for i in assets)
    total_liabilities = sum(i['value'] for i in liabilities)
    net = total_assets - total_liabilities
    conn.close()
    return render_template('net_worth.html', assets=assets, liabilities=liabilities,
                           total_assets=total_assets, total_liabilities=total_liabilities, net=net)

@app.route('/net-worth/delete/<name>', methods=['POST'])
def delete_net_worth(name):
    conn = get_db_connection()
    user_id = session['user_id']
    conn.execute("DELETE FROM assets_liabilities WHERE name=%s AND user_id=%s", (name, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for('net_worth'))

# ── Affordability ─────────────────────────────────────────────────────────────

@app.route('/affordability', methods=['GET', 'POST'])
def affordability():
    result = None
    if request.method == 'POST':
        user_id  = session['user_id']
        amount   = float(request.form['amount'])
        category = request.form.get('category', 'Overall')
        conn = get_db_connection()
        current_month = get_current_month()
        income   = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
        expenses = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
        today = datetime.now().day
        upcoming_bills = conn.execute("SELECT SUM(amount) as t FROM bills WHERE user_id=%s AND is_active=1 AND due_day>=%s", (user_id, today)).fetchone()['t'] or 0
        upcoming_emis  = conn.execute("SELECT SUM(monthly_emi) as t FROM loans WHERE user_id=%s AND remaining_installments>0 AND due_day>=%s", (user_id, today)).fetchone()['t'] or 0
        available_money     = income - expenses
        projected_remaining = available_money - (upcoming_bills + upcoming_emis) - amount
        budget_status = "No specific budget set."
        if category != 'Overall':
            budget = conn.execute("SELECT amount FROM budgets WHERE user_id=%s AND category=%s AND month=%s", (user_id, category, current_month)).fetchone()
            if budget:
                spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, category, current_month)).fetchone()['t'] or 0
                remaining = budget['amount'] - spent
                if amount > remaining:
                    budget_status = f"Warning: This exceeds your {category} budget by {amount - remaining:,.2f}."
                else:
                    budget_status = f"Good: Fits within your {category} budget."
        conn.close()
        if projected_remaining < 0:
            assessment = "Likely to strain the current budget"
            color, bg  = "text-danger", "bg-danger/10"
            reason = f"After upcoming bills and EMIs, you only have {available_money - (upcoming_bills + upcoming_emis):,.2f} available. This purchase would put you in the negative."
        elif projected_remaining < (income * 0.1):
            assessment = "Possible but needs caution"
            color, bg  = "text-warning-dark", "bg-warning/10"
            reason = "You can make this purchase, but it leaves you with less than 10% of your income as a buffer."
        else:
            assessment = "Comfortable"
            color, bg  = "text-success", "bg-success/10"
            reason = "You have enough discretionary money to comfortably make this purchase while covering your upcoming obligations."
        result = {
            'amount': amount, 'available': available_money,
            'obligations': upcoming_bills + upcoming_emis,
            'projected': projected_remaining, 'budget_status': budget_status,
            'assessment': assessment, 'color': color, 'bg': bg, 'reason': reason
        }
    return render_template('affordability.html', result=result)

# ── Smart Alerts ──────────────────────────────────────────────────────────────

@app.route('/api/alerts')
def get_alerts():
    """Generate rule-based financial alerts — no AI involved."""
    conn = get_db_connection()
    current_month = get_current_month()
    today   = datetime.now().day
    user_id = session['user_id']
    currency = get_setting(user_id, 'currency', '\u20b9')
    alerts  = []
    prev_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    # 1. Budget exceeded
    budgets_list = conn.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    for b in budgets_list:
        cat = b['category']
        if cat == 'Overall':
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
        else:
            spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, cat, current_month)).fetchone()['t'] or 0
        if b['amount'] > 0:
            pct = spent / b['amount'] * 100
            if pct > 100:
                alerts.append({'type': 'danger', 'icon': 'warning', 'msg': f'You have exceeded your {cat} budget by {currency}{spent - b["amount"]:,.0f}.'})
            elif pct > 85:
                alerts.append({'type': 'warning', 'icon': 'warning-circle', 'msg': f'Your {cat} budget is {pct:.0f}% used \u2014 only {currency}{b["amount"] - spent:,.0f} left.'})

    # 2. Category spending vs last month
    cats = conn.execute("SELECT category, SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s GROUP BY category", (user_id, current_month)).fetchall()
    for c in cats:
        prev = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, c['category'], prev_month)).fetchone()['t'] or 0
        if prev > 0:
            change_pct = (c['t'] - prev) / prev * 100
            if change_pct > 25:
                alerts.append({'type': 'warning', 'icon': 'trend-up', 'msg': f'Your {c["category"]} spending is {change_pct:.0f}% higher than last month.'})

    # 3. Upcoming bills (within 7 days)
    bills_list = conn.execute("SELECT * FROM bills WHERE user_id=%s AND is_active=1 AND due_day>=%s", (user_id, today)).fetchall()
    for b in bills_list:
        days_left = b['due_day'] - today
        if days_left <= 7:
            if days_left == 0:
                alerts.append({'type': 'danger',  'icon': 'lightning', 'msg': f'Your {b["name"]} bill of {currency}{b["amount"]:,.0f} is due today!'})
            elif days_left == 1:
                alerts.append({'type': 'danger',  'icon': 'lightning', 'msg': f'Your {b["name"]} bill of {currency}{b["amount"]:,.0f} is due tomorrow.'})
            else:
                alerts.append({'type': 'warning', 'icon': 'lightning', 'msg': f'Your {b["name"]} bill ({currency}{b["amount"]:,.0f}) is due in {days_left} days.'})

    # 4. Upcoming EMIs
    loans_list = conn.execute("SELECT * FROM loans WHERE user_id=%s AND remaining_installments>0 AND due_day>=%s", (user_id, today)).fetchall()
    for loan in loans_list:
        days_left = loan['due_day'] - today
        if days_left <= 7:
            if days_left == 0:
                alerts.append({'type': 'danger', 'icon': 'bank', 'msg': f'EMI for {loan["name"]} ({currency}{loan["monthly_emi"]:,.0f}) is due today!'})
            elif days_left == 1:
                alerts.append({'type': 'danger', 'icon': 'bank', 'msg': f'EMI for {loan["name"]} ({currency}{loan["monthly_emi"]:,.0f}) is due tomorrow.'})
            else:
                alerts.append({'type': 'info',   'icon': 'bank', 'msg': f'EMI for {loan["name"]} ({currency}{loan["monthly_emi"]:,.0f}) is due in {days_left} days.'})

    # 5. Savings improvement alert
    income      = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses    = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    prev_income = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, prev_month)).fetchone()['t'] or 0
    prev_exp    = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, prev_month)).fetchone()['t'] or 0
    curr_savings = income - expenses
    prev_savings = prev_income - prev_exp
    if curr_savings > prev_savings and prev_savings >= 0:
        alerts.append({'type': 'success', 'icon': 'trend-up', 'msg': f'You saved {currency}{curr_savings - prev_savings:,.0f} more this month than last month. Great work!'})

    # 6. Goals near completion
    goals_list = conn.execute("SELECT * FROM goals WHERE user_id=%s AND target_amount>0", (user_id,)).fetchall()
    for g in goals_list:
        pct = g['current_amount'] / g['target_amount'] * 100
        if 90 <= pct < 100:
            alerts.append({'type': 'success', 'icon': 'flag', 'msg': f'You are close to reaching your "{g["name"]}" goal \u2014 {pct:.0f}% complete!'})

    # 7. Total subscription cost info
    sub_total = conn.execute("SELECT SUM(amount) as t FROM bills WHERE user_id=%s AND is_active=1 AND frequency='monthly'", (user_id,)).fetchone()['t'] or 0
    if sub_total > 0:
        alerts.append({'type': 'info', 'icon': 'credit-card', 'msg': f'Your recurring monthly bills total {currency}{sub_total:,.0f}.'})

    conn.close()
    return jsonify(alerts)

# ── Financial Insights (AI + Fallback) ────────────────────────────────────────

def generate_fallback_insight(income, expenses, savings, top_categories, budgets, upcoming_obligations, currency='\u20b9'):
    """Deterministic, rule-based insight engine — no AI, no internet required."""
    parts = []
    savings_rate = (savings / income * 100) if income > 0 else 0

    # 1. Over-budget check
    over_budget = []
    for cat, budget_amt in budgets.items():
        if cat in top_categories and top_categories[cat] > budget_amt:
            over_budget.append((cat, top_categories[cat] - budget_amt, top_categories[cat], budget_amt))

    if over_budget:
        cat, over, spent, budget_amt = over_budget[0]
        parts.append(f"Your {cat} spending is {currency}{spent:,.0f} this month, which is {currency}{over:,.0f} over your {currency}{budget_amt:,.0f} budget.")
    elif top_categories:
        top_cat = max(top_categories, key=top_categories.get)
        parts.append(f"Your biggest expense this month is {top_cat} at {currency}{top_categories[top_cat]:,.0f}.")

    # 2. Savings health
    if income == 0:
        parts.append("Add your income transactions to get a full picture of your savings health.")
    elif savings < 0:
        parts.append(f"Your expenses exceed your income by {currency}{abs(savings):,.0f} this month \u2014 try to reduce discretionary spending urgently.")
    elif savings_rate < 10:
        parts.append(f"You are saving only {savings_rate:.0f}% of your income. Aim for at least 20% to build a healthy financial buffer.")
    elif savings_rate >= 20:
        parts.append(f"You are saving {savings_rate:.0f}% of your income this month \u2014 that's a great habit to keep up!")
    else:
        parts.append(f"You have saved {currency}{savings:,.0f} so far this month ({savings_rate:.0f}% of income).")

    # 3. Upcoming obligations
    if upcoming_obligations > 0:
        if upcoming_obligations > savings:
            parts.append(f"Watch out \u2014 your upcoming EMIs and bills total {currency}{upcoming_obligations:,.0f}, which is more than your current savings. Plan accordingly.")
        else:
            parts.append(f"You have {currency}{upcoming_obligations:,.0f} in upcoming bills and EMIs still due this month.")

    return " ".join(parts)

@app.route('/api/financial-insights')
def financial_insights():
    user_id = session['user_id']
    conn = get_db_connection()
    current_month = get_current_month()
    today    = datetime.now().day
    currency = get_setting(user_id, 'currency', '\u20b9')

    income   = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    savings  = income - expenses

    cats = conn.execute("SELECT category, SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s GROUP BY category ORDER BY t DESC LIMIT 5", (user_id, current_month)).fetchall()
    top_categories = {c['category']: c['t'] for c in cats}

    budgets_list = conn.execute("SELECT category, amount FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    budgets      = {b['category']: b['amount'] for b in budgets_list}

    emis      = conn.execute("SELECT SUM(monthly_emi) as t FROM loans WHERE user_id=%s AND remaining_installments>0 AND due_day>=%s", (user_id, today)).fetchone()['t'] or 0
    bills_due = conn.execute("SELECT SUM(amount) as t FROM bills WHERE user_id=%s AND is_active=1 AND due_day>=%s", (user_id, today)).fetchone()['t'] or 0
    upcoming_obligations = emis + bills_due
    conn.close()

    # Try Gemini AI if key is configured
    if GEMINI_API_KEY:
        prompt = f"""You are a helpful, concise personal finance assistant. Based on the user's data for this month, write 2-3 sentences of insight.
Data:
- Income: {currency}{income:,.0f}
- Expenses: {currency}{expenses:,.0f}
- Savings: {currency}{savings:,.0f}
- Top spending categories: {', '.join([f"{k} ({currency}{v:,.0f})" for k,v in top_categories.items()]) or 'None'}
- Budgets: {', '.join([f"{k}: {currency}{v:,.0f}" for k,v in budgets.items()]) or 'None set'}
- Upcoming EMIs & bills due this month: {currency}{upcoming_obligations:,.0f}

Instructions: Be friendly and direct. Focus on the most actionable observation. No Markdown, no bullet points. Plain sentences only."""
        url  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={GEMINI_API_KEY}"
        data = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
        }).encode('utf-8')
        try:
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=8) as response:
                result = json.loads(response.read())
                text = result['candidates'][0]['content']['parts'][0]['text'].strip()
                return jsonify({'insight': text, 'ai_used': True})
        except Exception as e:
            print(f"--- GEMINI AI ERROR ---: {e}")
            if hasattr(e, 'read'):
                print(e.read().decode('utf-8'))
            pass  # Fall through to deterministic fallback

    insight = generate_fallback_insight(income, expenses, savings, top_categories, budgets, upcoming_obligations, currency)
    return jsonify({'insight': insight, 'ai_used': False})

# ── Export ────────────────────────────────────────────────────────────────────

@app.route('/export/csv')
def export_csv():
    """Export all transactions as a UTF-8 CSV file."""
    conn = get_db_connection()
    user_id = session['user_id']
    rows = conn.execute("SELECT date, type, category, amount, payment_method, description, notes FROM transactions WHERE user_id=%s ORDER BY date DESC", (user_id,)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv_module.writer(output)
    writer.writerow(['Date', 'Type', 'Category', 'Amount', 'Payment Method', 'Description', 'Notes'])
    for r in rows:
        writer.writerow([r['date'], r['type'], r['category'], r['amount'], r['payment_method'], r['description'], r['notes']])
    csv_bytes = output.getvalue().encode('utf-8-sig')
    response = make_response(csv_bytes)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = 'attachment; filename=my_finances_transactions.csv'
    return response

@app.route('/export/json')
def export_json():
    """Export all user data as a JSON backup file."""
    conn = get_db_connection()
    user_id = session['user_id']
    data = {}
    for table in ['transactions', 'budgets', 'goals', 'loans', 'bills', 'assets_liabilities', 'categories']:
        rows = conn.execute(f"SELECT * FROM {table} WHERE user_id=%s", (user_id,)).fetchall()
        data[table] = [dict(row) for row in rows]
    conn.close()
    import flask
    json_str = flask.current_app.json.dumps(data, indent=2)
    response = make_response(json_str)
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = 'attachment; filename=my_finances_backup.json'
    return response

# ── Settings ──────────────────────────────────────────────────────────────────

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    msg = None
    user_id = session['user_id']
    conn = get_db_connection()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'clear_all':
            for table in ['transactions', 'budgets', 'goals', 'loans', 'bills', 'assets_liabilities']:
                conn.execute(f"DELETE FROM {table} WHERE user_id=%s", (user_id,))
            conn.commit()
            msg = 'All data has been cleared.'
        elif action == 'save_preferences':
            currency = request.form.get('currency', '\u20b9')
            set_setting(user_id, 'currency', currency)
            msg = 'Preferences saved.'
        elif action == 'update_profile':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            email    = request.form.get('email', '').strip().lower()
            if username:
                try:
                    conn.execute("UPDATE users SET username=%s WHERE id=%s", (username, user_id))
                    session['username'] = username
                    msg = 'Profile updated.'
                except psycopg2.IntegrityError:
                    msg = 'Username already exists.'
            if email:
                conn.execute("UPDATE users SET email=%s WHERE id=%s", (email, user_id))
                if not msg:
                    msg = 'Profile updated.'
            if password:
                hashed = generate_password_hash(password)
                conn.execute("UPDATE users SET password=%s WHERE id=%s", (hashed, user_id))
                msg = 'Profile and password updated.'
            conn.commit()
        elif action == 'add_category':
            name   = request.form.get('name', '').strip()
            c_type = request.form.get('type')
            if name and c_type:
                conn.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, %s)", (user_id, name, c_type))
                conn.commit()
                msg = 'Category added.'
        elif action == 'delete_category':
            cat_id = request.form.get('category_id')
            conn.execute("DELETE FROM categories WHERE id=%s AND user_id=%s", (cat_id, user_id))
            conn.commit()
            msg = 'Category deleted.'
        elif action == 'import_json':
            if 'import_file' in request.files:
                file = request.files['import_file']
                if file.filename != '':
                    try:
                        data = json.load(file)
                        if 'transactions' in data:
                            for t in data['transactions']:
                                conn.execute('''
                                    INSERT INTO transactions (user_id, amount, type, category, date, payment_method, description, notes)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ''', (user_id, t['amount'], t['type'], t['category'], t['date'],
                                      t.get('payment_method', ''), t.get('description', ''), t.get('notes', '')))
                            conn.commit()
                            msg = 'Data imported successfully.'
                    except Exception as e:
                        msg = f'Error importing data: {e}'
    expense_cats = conn.execute("SELECT * FROM categories WHERE user_id=%s AND type='expense' ORDER BY name", (user_id,)).fetchall()
    income_cats  = conn.execute("SELECT * FROM categories WHERE user_id=%s AND type='income' ORDER BY name",  (user_id,)).fetchall()
    user_info    = conn.execute("SELECT username, email FROM users WHERE id=%s", (user_id,)).fetchone()
    conn.close()
    return render_template('settings.html', msg=msg, expense_cats=expense_cats, income_cats=income_cats, user_info=user_info)

# ── Reports ───────────────────────────────────────────────────────────────────

@app.route('/reports')
def reports():
    conn = get_db_connection()
    current_month = request.args.get('month', get_current_month())
    user_id = session['user_id']
    income   = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    expenses = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    savings  = income - expenses
    savings_rate = (savings / income * 100) if income > 0 else 0
    top_categories = conn.execute("""
        SELECT category, SUM(amount) as total FROM transactions
        WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s
        GROUP BY category ORDER BY total DESC LIMIT 8
    """, (user_id, current_month)).fetchall()
    budgets_list = conn.execute("SELECT * FROM budgets WHERE user_id=%s AND month=%s", (user_id, current_month)).fetchall()
    budget_data = []
    for b in budgets_list:
        spent = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, b['category'], current_month)).fetchone()['t'] or 0
        budget_data.append({'category': b['category'], 'budget': b['amount'], 'spent': spent, 'over': spent > b['amount']})
    goals_list = conn.execute("SELECT * FROM goals WHERE user_id=%s", (user_id,)).fetchall()
    loans_list = conn.execute("SELECT * FROM loans WHERE user_id=%s", (user_id,)).fetchall()
    conn.close()
    return render_template('reports.html',
        income=income, expenses=expenses, savings=savings, savings_rate=savings_rate,
        top_categories=top_categories, budget_data=budget_data,
        goals=goals_list, loans=loans_list, current_month=current_month)

# ── Comparison (What Changed) ─────────────────────────────────────────────────

@app.route('/comparison')
def comparison():
    conn = get_db_connection()
    user_id = session['user_id']
    current_month  = get_current_month()
    prev_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    curr_inc = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    curr_exp = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, current_month)).fetchone()['t'] or 0
    prev_inc = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='income' AND substring(date from 1 for 7)=%s", (user_id, prev_month)).fetchone()['t'] or 0
    prev_exp = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND substring(date from 1 for 7)=%s", (user_id, prev_month)).fetchone()['t'] or 0
    curr_sav = curr_inc - curr_exp
    prev_sav = prev_inc - prev_exp
    categories = conn.execute("SELECT DISTINCT category FROM transactions WHERE user_id=%s AND type='expense' AND (substring(date from 1 for 7)=%s OR substring(date from 1 for 7)=%s)", (user_id, current_month, prev_month)).fetchall()
    cat_data = []
    for c in categories:
        cat   = c['category']
        c_amt = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, cat, current_month)).fetchone()['t'] or 0
        p_amt = conn.execute("SELECT SUM(amount) as t FROM transactions WHERE user_id=%s AND type='expense' AND category=%s AND substring(date from 1 for 7)=%s", (user_id, cat, prev_month)).fetchone()['t'] or 0
        if c_amt > 0 or p_amt > 0:
            cat_data.append({'category': cat, 'current': c_amt, 'previous': p_amt, 'diff': c_amt - p_amt})
    cat_data.sort(key=lambda x: x['current'], reverse=True)
    conn.close()
    return render_template('comparison.html',
        current_month=current_month, prev_month=prev_month,
        curr_inc=curr_inc, curr_exp=curr_exp, curr_sav=curr_sav,
        prev_inc=prev_inc, prev_exp=prev_exp, prev_sav=prev_sav,
        cat_data=cat_data)

# ── Daily View ────────────────────────────────────────────────────────────────

@app.route('/daily')
def daily():
    conn = get_db_connection()
    user_id = session['user_id']
    current_month = request.args.get('month', get_current_month())
    daily_data = conn.execute("""
        SELECT date,
               SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
        FROM transactions
        WHERE user_id=%s AND substring(date from 1 for 7)=%s
        GROUP BY date ORDER BY date DESC
    """, (user_id, current_month)).fetchall()
    days = []
    for d in daily_data:
        txns = conn.execute("SELECT * FROM transactions WHERE user_id=%s AND date=%s ORDER BY id DESC", (user_id, d['date'])).fetchall()
        days.append({'date': d['date'], 'income': d['income'], 'expense': d['expense'], 'transactions': txns})
    conn.close()
    return render_template('daily.html', days=days, current_month=current_month)

# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, port=5000)
