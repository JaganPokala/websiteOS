"""
Create the product tables (users / conversations / messages) in Neon.
Safe to re-run — every statement uses IF NOT EXISTS.

    .venv\\Scripts\\python.exe init_db.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg

load_dotenv()

uri = os.getenv("POSTGRES_URI")
if not uri:
    sys.exit("POSTGRES_URI missing from .env")

sql = Path("schema.sql").read_text(encoding="utf-8")

# psycopg sends one command per execute(), so split the script on ';'.
statements = [s.strip() for s in sql.split(";") if s.strip()]

with psycopg.connect(uri, connect_timeout=20, autocommit=True) as conn:
    for stmt in statements:
        conn.execute(stmt)

print(f"Done — ran {len(statements)} statements. Product tables are ready.")