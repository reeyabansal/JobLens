"""SQLite persistence. Stdlib only — no ORM, keeps the footprint tiny."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Job, STATUSES

DB_PATH = Path(__file__).resolve().parent.parent / "jobhunt.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    dedup_key     TEXT UNIQUE NOT NULL,
    content_key   TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    location      TEXT DEFAULT '',
    remote        INTEGER DEFAULT 0,
    url           TEXT NOT NULL,
    description   TEXT DEFAULT '',
    posted_at     TEXT,
    start_date    TEXT,
    start_year    INTEGER,
    status        TEXT NOT NULL DEFAULT 'to_apply',
    ats_score     REAL,
    analysis      TEXT,               -- cached JSON from the scorer
    notified      INTEGER DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_content ON jobs(content_key);

-- tombstones so deleted jobs don't get re-ingested on the next run
CREATE TABLE IF NOT EXISTS dismissed (
    dedup_key   TEXT PRIMARY KEY,
    content_key TEXT,
    dismissed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dismissed_content ON dismissed(content_key);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def insert_job(conn: sqlite3.Connection, job: Job) -> Optional[str]:
    """Insert a job. Returns the new row id, or None if it was a duplicate."""
    dk = job.dedup_key()
    ck = job.content_key()
    # skip anything the user previously deleted (tombstoned)
    tomb = conn.execute(
        "SELECT 1 FROM dismissed WHERE dedup_key = ? OR content_key = ?", (dk, ck)
    ).fetchone()
    if tomb:
        return None
    # dedup by native key first, then by content (same role/company/location)
    existing = conn.execute(
        "SELECT id FROM jobs WHERE dedup_key = ? OR content_key = ?", (dk, ck)
    ).fetchone()
    if existing:
        return None

    new_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO jobs (id, dedup_key, content_key, source, source_job_id,
               title, company, location, remote, url, description, posted_at,
               start_date, start_year, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_id, dk, job.content_key(), job.source, job.source_job_id,
            job.title, job.company, job.location, int(job.remote), job.url,
            job.description, job.posted_at, job.start_date, job.start_year,
            "to_apply", _now(),
        ),
    )
    conn.commit()
    return new_id


def list_jobs(conn, status: Optional[str] = None, order_by: str = "score") -> list[dict]:
    q = "SELECT * FROM jobs"
    params: list = []
    if status and status != "all":
        q += " WHERE status = ?"
        params.append(status)
    if order_by == "score":
        q += " ORDER BY ats_score IS NULL, ats_score DESC, created_at DESC"
    else:
        q += " ORDER BY created_at DESC"
    rows = conn.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_job(conn, job_id: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(r) if r else None


def update_status(conn, job_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    cur = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    return cur.rowcount > 0


def update_description(conn, job_id: str, description: str) -> None:
    conn.execute("UPDATE jobs SET description = ? WHERE id = ?", (description, job_id))
    conn.commit()


def save_analysis(conn, job_id: str, score: float, analysis: dict) -> None:
    conn.execute(
        "UPDATE jobs SET ats_score = ?, analysis = ? WHERE id = ?",
        (score, json.dumps(analysis), job_id),
    )
    conn.commit()


def delete_job(conn, job_id: str) -> bool:
    row = conn.execute(
        "SELECT dedup_key, content_key FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "INSERT OR REPLACE INTO dismissed (dedup_key, content_key, dismissed_at) "
        "VALUES (?,?,?)", (row["dedup_key"], row["content_key"], _now()),
    )
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return True


def unnotified(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM jobs WHERE notified = 0").fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_notified(conn, job_id: str) -> None:
    conn.execute("UPDATE jobs SET notified = 1 WHERE id = ?", (job_id,))
    conn.commit()


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["remote"] = bool(d.get("remote"))
    d["notified"] = bool(d.get("notified"))
    if d.get("analysis"):
        try:
            d["analysis"] = json.loads(d["analysis"])
        except (json.JSONDecodeError, TypeError):
            d["analysis"] = None
    return d
