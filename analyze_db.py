import re

with open(r'd:\My Finances\app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

output = []
output.append("--- STRFTIME/DATE USAGES ---")
for i, line in enumerate(lines):
    if 'strftime' in line or "date('now'" in line:
        output.append(f"{i+1}: {line.strip()}")

output.append("\n--- SQLITE INTEGRITY ERROR ---")
for i, line in enumerate(lines):
    if 'sqlite3.IntegrityError' in line:
        output.append(f"{i+1}: {line.strip()}")

output.append("\n--- LASTROWID USAGES ---")
for i, line in enumerate(lines):
    if 'lastrowid' in line:
        output.append(f"{i+1}: {line.strip()}")

output.append("\n--- ALL SQL QUERIES WITH '?' ---")
for i, line in enumerate(lines):
    if '?' in line and ('SELECT ' in line or 'INSERT ' in line or 'UPDATE ' in line or 'DELETE ' in line):
        output.append(f"{i+1}: {line.strip()}")

with open(r'd:\My Finances\analysis_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(output))
