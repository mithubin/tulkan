import sqlite3
import uuid
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get('TUL_DB_PATH', '/tul_data/db/tul.sqlite')


def uid() -> str:
    return str(uuid.uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db():
    path = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    _migrate()


def _migrate():
    alters = [
        'ALTER TABLE files ADD COLUMN listed INTEGER NOT NULL DEFAULT 1',
        "ALTER TABLE nc_targets ADD COLUMN direction TEXT NOT NULL DEFAULT 'push'",
        'ALTER TABLE nc_targets ADD COLUMN tool TEXT',
        'ALTER TABLE files ADD COLUMN grp TEXT',
    ]
    with get_conn() as conn:
        for sql in alters:
            try:
                conn.execute(sql)
            except Exception:
                pass


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  email       TEXT UNIQUE NOT NULL,
  pw_hash     TEXT NOT NULL,
  global_role TEXT NOT NULL DEFAULT 'user',
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_access (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tool    TEXT NOT NULL,
  allowed INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (user_id, tool)
);

CREATE TABLE IF NOT EXISTS user_themes (
  user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tool     TEXT NOT NULL,
  settings TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, tool)
);

CREATE TABLE IF NOT EXISTS files (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tool       TEXT NOT NULL,
  filename   TEXT NOT NULL,
  path       TEXT NOT NULL,
  size       INTEGER NOT NULL,
  mime       TEXT,
  category   TEXT NOT NULL CHECK(category IN ('input','output')),
  file_type  TEXT,
  retention  TEXT NOT NULL DEFAULT '1mo'
             CHECK(retention IN ('task','1w','1mo','user','perm')),
  created_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_user_tool ON files(user_id, tool);
CREATE INDEX IF NOT EXISTS idx_files_expires   ON files(expires_at);

CREATE TABLE IF NOT EXISTS nc_targets (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label      TEXT NOT NULL,
  url        TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nc_targets_user ON nc_targets(user_id);
"""


RETENTION_DAYS = {'task': 1, '1w': 7, '1mo': 30}


def retention_expires(retention: str) -> str | None:
    """Returns ISO expires_at string, or None for user/perm."""
    days = RETENTION_DAYS.get(retention)
    if days is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def cleanup_expired_files(file_root: str | None = None):
    """Delete DB entries and files where expires_at < now. Call on startup or via cron."""
    ts = now()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, path FROM files WHERE expires_at IS NOT NULL AND expires_at < ?", (ts,)
        ).fetchall()
        for row in rows:
            try:
                import pathlib
                p = pathlib.Path(row['path'])
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        if rows:
            ids = [r['id'] for r in rows]
            conn.execute(
                f"DELETE FROM files WHERE id IN ({','.join('?'*len(ids))})", ids
            )
