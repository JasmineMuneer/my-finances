import re

with open(r'd:\My Finances\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Imports
content = content.replace("import sqlite3", "import psycopg2")

# 2. SQLite exceptions
content = content.replace("sqlite3.IntegrityError", "psycopg2.IntegrityError")

# 3. Date replacements
content = content.replace("strftime('%Y-%m', date)", "substring(date from 1 for 7)")
content = content.replace("strftime('%Y-%m',date)", "substring(date from 1 for 7)")
content = content.replace("date >= date('now', '-6 months')", "date::date >= CURRENT_DATE - INTERVAL '6 months'")

# 4. Signup lastrowid
signup_old = """cursor = conn.execute('INSERT INTO users (username, password, email) VALUES (?, ?, ?)', (username, hashed, email))
        user_id = cursor.lastrowid"""
signup_new = """cursor = conn.execute('INSERT INTO users (username, password, email) VALUES (%s, %s, %s) RETURNING id', (username, hashed, email))
        user_id = cursor.fetchone()['id']"""
content = content.replace(signup_old, signup_new)

# 5. Question Marks replacement.
# Let's find all occurrences of `conn.execute(` and process the string inside.
# Actually, it's easier to just replace all `?` in the file, and then restore the ones in URLs and HTML/Text.
# Let's list the known non-SQL `?` occurrences in app.py:
# - URL in AI prompt: `generativelanguage.googleapis.com/...:generateContent?key=`
# - if row['value'] != RUPEE and row['value'] in ['â‚¹', '?']:
# - request.args.get('q', '').strip() ... wait, that doesn't have `?`.
# - if '?' in line ... (my own script doesn't matter, it's not in app.py).
# - "Forgot Password?" (HTML text... not in app.py)
# - ? in docstrings or comments.

# Let's write a safer replacer: 
lines = content.split('\n')
for i, line in enumerate(lines):
    # Skip URL line
    if "https://generativelanguage.googleapis.com" in line:
        continue
    # Skip char check line (though it's in database.py, not app.py)
    if "['â‚¹', '?']" in line:
        continue
    # If there is a ? and it looks like a SQL statement
    if 'execute(' in line or 'execute("""' in line or 'execute(\\'\\'\\'' in line or '?' in line:
        # Check if this line is part of a query
        # Actually, if we just replace "?" with "%s" in lines containing 'execute' or 'AND ' or 'WHERE ' or 'VALUES ' or 'SET ':
        if 'WHERE ' in line or 'VALUES ' in line or 'SET ' in line or 'execute(' in line or 'LIKE ?' in line:
            lines[i] = line.replace('?', '%s')
            
# Wait, some multiline queries have `?` on lines without `execute(`.
# A better way: replace ALL `?` in app.py, then fix the AI URL.
content = content.replace('?', '%s')
content = content.replace('generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent%skey=', 'generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key=')

with open(r'd:\My Finances\app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Conversion complete.")
