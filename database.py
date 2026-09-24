# -*- coding: utf-8 -*-
import sqlite3
import os
import hashlib

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'finances.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.text_factory = str
    return conn

def upgrade_db():
    conn = get_db_connection()
    try:
        # Check if users table exists
        users_exist = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not users_exist:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
            """)
        
        # Ensure default user exists
        default_user = conn.execute("SELECT id FROM users WHERE id=1").fetchone()
        if not default_user:
            # Create default user with blank password or some hash
            from werkzeug.security import generate_password_hash
            default_hash = generate_password_hash("password")
            try:
                conn.execute("INSERT INTO users (id, username, password) VALUES (1, 'default_user', ?)", (default_hash,))
            except:
                pass # might fail if 'default_user' exists with different id, not a big deal
            conn.commit()

        # Check if transactions has user_id
        txn_info = conn.execute("PRAGMA table_info(transactions)").fetchall()
        has_user_id = any(col['name'] == 'user_id' for col in txn_info)
        
        if not has_user_id:
            tables = ['transactions', 'budgets', 'goals', 'loans', 'bills', 'assets_liabilities']
            for t in tables:
                try:
                    conn.execute(f"ALTER TABLE {t} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                except Exception as e:
                    print(f"Migration error on {t}:", e)
            
            # Recreate settings table
            conn.execute("CREATE TABLE new_settings (user_id INTEGER NOT NULL DEFAULT 1, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(user_id, key))")
            conn.execute("INSERT INTO new_settings (user_id, key, value) SELECT 1, key, value FROM settings")
            conn.execute("DROP TABLE settings")
            conn.execute("ALTER TABLE new_settings RENAME TO settings")
            conn.commit()
            
        # Add categories table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL
            )
        """)
        
        # Populate default categories for any user that doesn't have any
        users = conn.execute("SELECT id FROM users").fetchall()
        for u in users:
            uid = u['id']
            has_cats = conn.execute("SELECT count(*) as c FROM categories WHERE user_id=?", (uid,)).fetchone()['c']
            if has_cats == 0:
                default_expenses = ['Food', 'Groceries', 'Shopping', 'Transport', 'Housing', 'Utilities', 'Entertainment', 'Healthcare', 'Other']
                default_incomes = ['Salary', 'Freelance', 'Investment', 'Other Income']
                for cat in default_expenses:
                    conn.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, 'expense')", (uid, cat))
                for cat in default_incomes:
                    conn.execute("INSERT INTO categories (user_id, name, type) VALUES (?, ?, 'income')", (uid, cat))
        
        # Add email column to users if missing
        user_cols = [col['name'] for col in conn.execute("PRAGMA table_info(users)").fetchall()]
        if 'email' not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
        
        # Add password_reset_tokens table if missing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL
            )
        """)
        
        conn.commit()

    except Exception as e:
        print("Database migration error:", e)
    finally:
        conn.close()

def init_db():
    if not os.path.exists(DB_PATH):
        conn = get_db_connection()
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()

    upgrade_db()

    # Always repair the currency symbol for all users (or just user 1 as default)
    # On Windows the terminal may write the rupee sign using cp1252 encoding,
    # so we detect any value that is NOT the correct Unicode character and fix it.
    RUPEE = '\u20b9'   # ₹
    conn = get_db_connection()
    # Check if any user has corrupted currency
    rows = conn.execute("SELECT user_id, value FROM settings WHERE key = 'currency'").fetchall()
    for row in rows:
        if row['value'] != RUPEE and row['value'] in ['â‚¹', '?']: # simple check
            conn.execute("UPDATE settings SET value = ? WHERE key = 'currency' AND user_id = ?", (RUPEE, row['user_id']))
    conn.commit()
    conn.close()

def get_setting(user_id, key, default=None):
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(user_id, key, value):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
        (user_id, key, str(value))
    )
    conn.commit()
    conn.close()
