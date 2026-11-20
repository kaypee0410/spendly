import os
import tempfile

import pytest

import database.db as db_module

# Importing app runs init_db()/seed_db() at module level. Point DB_PATH at a
# throwaway file first so the real expense_tracker.db is never touched.
db_module.DB_PATH = os.path.join(tempfile.mkdtemp(), "import.db")
# A fixed test key, so importing app doesn't warn about a missing SECRET_KEY.
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import app as flask_app  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "test.db"))
    db_module.init_db()
    db_module.seed_db()
    flask_app.config["TESTING"] = True
    # Feature tests post bare forms; tests/test_csrf.py switches this back on.
    monkeypatch.setitem(flask_app.config, "CSRF_ENABLED", False)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()
