import sqlite3
from datetime import datetime
from pathlib import Path


class Storage:
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id               TEXT PRIMARY KEY,
                    platform         TEXT NOT NULL,
                    title            TEXT NOT NULL,
                    company          TEXT,
                    location         TEXT,
                    contract_type    TEXT,
                    salary           TEXT,
                    description      TEXT,
                    url              TEXT NOT NULL,
                    date_posted      TEXT,
                    date_found       TEXT NOT NULL,
                    relevance_score  REAL DEFAULT 0,
                    notified         INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def job_exists(self, job_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return row is not None

    def save_job(self, job) -> bool:
        """Save a job. Returns True if inserted, False if already existed."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO jobs
                    (id, platform, title, company, location, contract_type,
                     salary, description, url, date_posted, date_found, relevance_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id, job.platform, job.title, job.company or "",
                job.location or "", job.contract_type or "", job.salary or "",
                job.description or "", job.url, job.date_posted or "",
                datetime.now().isoformat(), job.relevance_score,
            ))
            conn.commit()
            return cursor.rowcount > 0

    def mark_notified(self, job_id: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE jobs SET notified = 1 WHERE id = ?", (job_id,))
            conn.commit()

    def get_recent_jobs(self, limit: int = 20) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY date_found DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def count_jobs(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
            return row[0]
