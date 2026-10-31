import sqlite3
from datetime import date

from flask import current_app, g

# Python 3.12 deprecated the implicit date adapter/converter; register our own.
sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode("utf-8")))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after v1; brought onto existing databases idempotently.
_ADDED_COLUMNS = {
    "booking": [
        ("renter_email", "TEXT NOT NULL DEFAULT ''"),
        ("agreed_terms", "INTEGER NOT NULL DEFAULT 0"),
    ],
}


def _ensure_columns(db):
    for table, cols in _ADDED_COLUMNS.items():
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))
    _ensure_columns(db)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
