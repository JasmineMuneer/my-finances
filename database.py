import os
import psycopg2
from psycopg2.extras import DictCursor

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.pg.sql')

class Psycopg2ConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, vars=None):
        cur = self._conn.cursor()
        cur.execute(query, vars)
        return cur
        
    def executescript(self, script):
        cur = self._conn.cursor()
        cur.execute(script)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set. Cannot connect to PostgreSQL.")
    
    conn = psycopg2.connect(db_url, cursor_factory=DictCursor)
    # Autocommit is false by default in psycopg2, which matches sqlite3's behavior for DML
    return Psycopg2ConnectionWrapper(conn)

def init_db():
    conn = get_db_connection()
    try:
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            conn.execute(f.read())
        
        # Populate default categories for any user that doesn't have any
        users = conn.execute("SELECT id FROM users").fetchall()
        for u in users:
            uid = u['id']
            has_cats = conn.execute("SELECT count(*) as c FROM categories WHERE user_id=%s", (uid,)).fetchone()['c']
            if has_cats == 0:
                default_expenses = ['Food', 'Groceries', 'Shopping', 'Transport', 'Housing', 'Utilities', 'Entertainment', 'Healthcare', 'Other']
                default_incomes = ['Salary', 'Freelance', 'Investment', 'Other Income']
                for cat in default_expenses:
                    conn.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, 'expense')", (uid, cat))
                for cat in default_incomes:
                    conn.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, 'income')", (uid, cat))
        
        # Always repair the currency symbol for all users
        RUPEE = '\u20b9'
        rows = conn.execute("SELECT user_id, value FROM settings WHERE key = 'currency'").fetchall()
        for row in rows:
            if row['value'] != RUPEE and row['value'] in ['â‚¹', '?']:
                conn.execute("UPDATE settings SET value = %s WHERE key = 'currency' AND user_id = %s", (RUPEE, row['user_id']))
        conn.commit()
    finally:
        conn.close()

def get_setting(user_id, key, default=None):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE user_id = %s AND key = %s", (user_id, key)).fetchone()
        return row['value'] if row else default
    finally:
        conn.close()

def set_setting(user_id, key, value):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = EXCLUDED.value",
            (user_id, key, str(value))
        )
        conn.commit()
    finally:
        conn.close()
