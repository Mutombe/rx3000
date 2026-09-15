"""The application, running in-process against a copy of the local database.

Import this before anything from `app`: it takes a consistent snapshot of
backend/rx3000.db (the write-ahead log included, through SQLite's backup API),
points DATABASE_URL at the copy, and only then imports the application — so
nothing a test does can reach the working database.

`client()` starts the application the way uvicorn does, which is what runs the
migrations. Constructing a TestClient without starting it skips them, and a
test then queries a schema one change behind the code: it passed until a model
gained a column, and then failed for a reason that had nothing to do with it.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
_dir = tempfile.mkdtemp(prefix="rx5000-test-")
SNAPSHOT = Path(_dir) / "snapshot.db"
with sqlite3.connect(str(BACKEND / "rx3000.db")) as _src, sqlite3.connect(str(SNAPSHOT)) as _dst:
    _src.backup(_dst)
os.environ["DATABASE_URL"] = f"sqlite:///{SNAPSHOT.as_posix()}"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

_client: TestClient | None = None


def client() -> TestClient:
    """Started (so migrated) and signed in as the administrator."""
    global _client
    if _client is None:
        c = TestClient(app)
        c.__enter__()                                   # runs the lifespan
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        _client = c
    return _client


def sql(query: str, params: tuple = ()):
    """Read the snapshot directly.

    Every model is filtered by pharmacy, and outside a request no pharmacy is
    in force, so an ORM read here returns nothing — and an "unchanged" check
    would pass on nothing. Plain SQL sees what is actually stored.
    """
    with sqlite3.connect(str(SNAPSHOT)) as c:
        return c.execute(query, params).fetchall()


def execute(query: str, params: tuple = ()) -> None:
    with sqlite3.connect(str(SNAPSHOT)) as c:
        c.execute(query, params)
