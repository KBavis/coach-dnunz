"""Tiny SQLite library of VODs."""
import os, sqlite3, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("COACH_DATA", ROOT / "data"))   # library location; override for tests
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
    source_url TEXT DEFAULT '',
    our_side TEXT DEFAULT 'l'      -- which HUD score is the team being coached: 'l' or 'r'
)
"""


def connect():
    VODS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "library.db", check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(vods)")}
    if "source_url" not in cols:                                  # older libraries
        con.execute("ALTER TABLE vods ADD COLUMN source_url TEXT DEFAULT ''")
    if "our_side" not in cols:
        con.execute("ALTER TABLE vods ADD COLUMN our_side TEXT DEFAULT 'l'")
    return con


def new_id():
    return uuid.uuid4().hex[:10]


def now():
    return time.time()
