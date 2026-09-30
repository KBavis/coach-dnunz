"""Tiny SQLite library of VODs."""
import sqlite3, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VODS = DATA / "vods"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vods (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued | processing | ready | failed
    stage TEXT DEFAULT '',
    pct REAL DEFAULT 0,
    error TEXT DEFAULT '',
    duration REAL DEFAULT 0,
    created_at REAL NOT NULL,
    source_url TEXT DEFAULT ''
)
"""


def connect():
    VODS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "library.db", check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    if "source_url" not in {r[1] for r in con.execute("PRAGMA table_info(vods)")}:
        con.execute("ALTER TABLE vods ADD COLUMN source_url TEXT DEFAULT ''")   # older libraries
    return con


def new_id():
    return uuid.uuid4().hex[:10]


def now():
    return time.time()
