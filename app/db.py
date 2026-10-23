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

# Allowlists: only these identifiers may appear in DDL statements.
# This prevents SQL injection if _ADDED_COLUMNS is ever populated from untrusted input.
_VALID_TABLES: frozenset[str] = frozenset({"item", "booking", "blackout", "setting"})
_VALID_COLUMNS: frozenset[str] = frozenset(
    {"id", "name", "slug", "description", "photo_path", "rate_amount", "rate_unit",
     "deposit_amount", "is_active", "created_at", "item_id", "renter_name",
     "renter_contact", "renter_email", "start_date", "end_date", "status",
     "quoted_amount", "notes", "agreed_terms", "is_paid", "paid_amount",
     "payment_method", "payment_ref", "paid_at", "reason", "key", "value"}
)


def _validate_identifier(name: str) -> str:
    """Validate an SQL identifier against the allowlist. Returns *name* on success."""
    if name not in _VALID_TABLES and name not in _VALID_COLUMNS:
        raise ValueError(f"Disallowed SQL identifier: {name!r}")
    return name


def _ensure_columns(db):
    for table, cols in _ADDED_COLUMNS.items():
        _validate_identifier(table)
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({_validate_identifier(table)})")}
        for name, decl in cols:
            _validate_identifier(name)
            if name not in have:
                # decl is trusted — it comes from our own source code, not user input.
                db.execute(f"ALTER TABLE {_validate_identifier(table)} ADD COLUMN {name} {decl}")


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))
    _ensure_columns(db)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
