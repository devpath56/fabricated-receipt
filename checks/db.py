import sqlite3
from pathlib import Path


def get_conn(db_path: str) -> sqlite3.Connection:
    if not Path(db_path).exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run etl/upsert.py and etl/seed_table3.py first."
        )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
