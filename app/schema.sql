-- RentStuff schema. Non-destructive: safe to re-run (idempotent).

CREATE TABLE IF NOT EXISTS item (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  name           TEXT    NOT NULL,
  slug           TEXT    NOT NULL UNIQUE,
  description    TEXT    NOT NULL DEFAULT '',
  photo_path     TEXT,
  rate_amount    REAL    NOT NULL DEFAULT 0,
  rate_unit      TEXT    NOT NULL DEFAULT 'day',   -- 'day' | 'week' | 'flat'
  deposit_amount REAL    NOT NULL DEFAULT 0,
  is_active      INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS booking (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id        INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  renter_name    TEXT    NOT NULL,
  renter_contact TEXT    NOT NULL DEFAULT '',
  start_date     DATE    NOT NULL,
  end_date       DATE    NOT NULL,
  status         TEXT    NOT NULL DEFAULT 'requested', -- requested|confirmed|returned|cancelled
  quoted_amount  REAL    NOT NULL DEFAULT 0,
  deposit_amount REAL    NOT NULL DEFAULT 0,
  notes          TEXT    NOT NULL DEFAULT '',
  -- billing tracking (folded into booking for v1; split to a payments table
  -- only when Stripe or partial payments arrive)
  is_paid        INTEGER NOT NULL DEFAULT 0,
  paid_amount    REAL    NOT NULL DEFAULT 0,
  payment_method TEXT,                              -- cash|venmo|zoho|stripe|...
  payment_ref    TEXT,                              -- Zoho invoice # now, Stripe id later
  paid_at        TEXT,
  created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS blackout (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id    INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  start_date DATE    NOT NULL,
  end_date   DATE    NOT NULL,
  reason     TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_booking_item   ON booking(item_id);
CREATE INDEX IF NOT EXISTS idx_booking_status ON booking(status);
CREATE INDEX IF NOT EXISTS idx_blackout_item  ON blackout(item_id);
