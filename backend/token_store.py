"""SQLite-backed store for per-session Outlook tokens.

Tokens used to live in a module-level dict, which meant they vanished on every
restart and were shared by every caller of the backend. Here each browser
session gets its own row, keyed by a random id the frontend generates.

Set TOKEN_DB_PATH to a path on a persistent disk in production — on an
ephemeral filesystem the tokens survive process restarts but not redeploys.
"""

import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("TOKEN_DB_PATH", os.path.join(os.path.dirname(__file__), "tokens.db"))

# Sessions untouched for this long are dropped; Azure refresh tokens go stale
# well before then anyway.
MAX_AGE_SECONDS = 90 * 24 * 3600

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outlook_sessions (
                session_id    TEXT PRIMARY KEY,
                access_token  TEXT NOT NULL,
                refresh_token TEXT,
                expires_at    REAL NOT NULL,
                account       TEXT,
                updated_at    REAL NOT NULL
            )
            """
        )
        _conn.commit()
    return _conn


def save(session_id: str, access_token: str, refresh_token: str | None,
         expires_at: float, account: str | None) -> None:
    with _lock:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO outlook_sessions
                (session_id, access_token, refresh_token, expires_at, account, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                access_token  = excluded.access_token,
                -- Azure omits the refresh token on some responses; keep the old one.
                refresh_token = COALESCE(excluded.refresh_token, outlook_sessions.refresh_token),
                expires_at    = excluded.expires_at,
                account       = COALESCE(excluded.account, outlook_sessions.account),
                updated_at    = excluded.updated_at
            """,
            (session_id, access_token, refresh_token, expires_at, account, time.time()),
        )
        conn.commit()


def load(session_id: str) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT * FROM outlook_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def delete(session_id: str) -> None:
    with _lock:
        conn = _connect()
        conn.execute("DELETE FROM outlook_sessions WHERE session_id = ?", (session_id,))
        conn.commit()


def purge_stale() -> int:
    cutoff = time.time() - MAX_AGE_SECONDS
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM outlook_sessions WHERE updated_at < ?", (cutoff,))
        conn.commit()
    return cur.rowcount


def stats() -> dict:
    """Counts for the health endpoint. Raises if the store is unusable."""
    with _lock:
        row = _connect().execute(
            "SELECT COUNT(*) AS total, SUM(expires_at > ?) AS live FROM outlook_sessions",
            (time.time(),),
        ).fetchone()
    return {"sessions": row["total"], "live_access_tokens": row["live"] or 0}
