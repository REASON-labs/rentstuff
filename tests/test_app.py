"""A couple of smoke tests to prove the app wires together."""


def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_admin_requires_login(client):
    # unauthenticated admin should redirect to login
    resp = client.get("/admin/")
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]


def test_request_flow_creates_booking(app, client, stamp):
    from app import models
    with app.app_context():
        models.create_item("Test Truck", "test-truck", "", 10, "day", 0)

    resp = client.post("/item/test-truck", data={
        "form_stamp": stamp(),
        "renter_name": "Sam",
        "renter_contact": "sam@example.com",
        "agree": "1",
        "start_date": "2098-09-01",
        "end_date": "2098-09-04",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from app import models
        bookings, _ = models.list_bookings()
        assert len(bookings) == 1
        assert bookings[0]["renter_name"] == "Sam"
        assert bookings[0]["quoted_amount"] == 30.0  # 3 nights * 10


def _login(client):
    with client.session_transaction() as sess:
        sess["is_admin"] = True


def test_slug_autogenerates_and_dedupes(app, client):
    _login(client)
    client.post("/admin/items/new", data={"name": "Camp Stove", "rate_amount": "5",
                                           "rate_unit": "day", "deposit_amount": "0"})
    client.post("/admin/items/new", data={"name": "Camp Stove!", "rate_amount": "5",
                                           "rate_unit": "day", "deposit_amount": "0"})
    with app.app_context():
        from app import models
        slugs = sorted(i["slug"] for i in models.list_items())
    assert "camp-stove" in slugs
    assert "camp-stove-2" in slugs  # collision handled, no error


def test_pick_default_image(app, client):
    _login(client)
    client.post("/admin/items/new", data={"name": "Grill", "rate_amount": "8",
                                           "rate_unit": "day", "deposit_amount": "0",
                                           "default_image": "img/defaults/03.svg"})
    with app.app_context():
        from app import models
        item = models.get_item_by_slug("grill")
    assert item["photo_path"] == "img/defaults/03.svg"


def test_upload_photo(app, client):
    import io
    from PIL import Image
    _login(client)
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 100, 40)).save(buf, "PNG")
    buf.seek(0)
    client.post("/admin/items/new", data={
        "name": "Ladder", "rate_amount": "4", "rate_unit": "day", "deposit_amount": "0",
        "photo": (buf, "ladder.png"),
    }, content_type="multipart/form-data")
    with app.app_context():
        from app import models
        item = models.get_item_by_slug("ladder")
        assert item["photo_path"].startswith("uploads/")
        import os
        from flask import current_app
        path = os.path.join(current_app.config["UPLOAD_DIR"],
                            item["photo_path"].split("/", 1)[1])
        assert os.path.exists(path)
    # and it serves
    served = client.get("/media/" + item["photo_path"].split("/", 1)[1])
    assert served.status_code == 200


# ---------- item edit ----------

def test_item_edit_updates_but_keeps_slug(app, client):
    _login(client)
    with app.app_context():
        from app import models
        iid = models.create_item("Old Name", "old-name", "", 5, "day", 0)
    client.post(f"/admin/items/{iid}/edit", data={
        "name": "New Name", "rate_amount": "9", "rate_unit": "week", "deposit_amount": "3"})
    with app.app_context():
        from app import models
        it = models.get_item(iid)
    assert it["name"] == "New Name" and it["rate_amount"] == 9 and it["rate_unit"] == "week"
    assert it["slug"] == "old-name"  # slug stable across rename


def test_item_edit_keeps_then_removes_photo(app, client):
    _login(client)
    with app.app_context():
        from app import models
        iid = models.create_item("Grill", "grill", "", 5, "day", 0,
                                 photo_path="img/defaults/02.svg")
    client.post(f"/admin/items/{iid}/edit", data={  # no image fields -> keep
        "name": "Grill", "rate_amount": "5", "rate_unit": "day", "deposit_amount": "0"})
    with app.app_context():
        from app import models
        assert models.get_item(iid)["photo_path"] == "img/defaults/02.svg"
    client.post(f"/admin/items/{iid}/edit", data={  # remove
        "name": "Grill", "rate_amount": "5", "rate_unit": "day",
        "deposit_amount": "0", "remove_photo": "1"})
    with app.app_context():
        from app import models
        assert not models.get_item(iid)["photo_path"]


# ---------- confirm-time conflict re-check ----------

def test_confirm_rechecks_conflict(app, client):
    _login(client)
    with app.app_context():
        from app import models
        iid = models.create_item("Van", "van", "", 10, "day", 0)
        models.create_booking(item_id=iid, renter_name="A", renter_contact="",
                              start_date="2098-09-01", end_date="2098-09-05",
                              quoted_amount=40, deposit_amount=0, status="confirmed")
        b = models.create_booking(item_id=iid, renter_name="B", renter_contact="",
                                  start_date="2098-09-03", end_date="2098-09-07",
                                  quoted_amount=40, deposit_amount=0, status="requested")
    client.post(f"/admin/bookings/{b}/status", data={"status": "confirmed"})
    with app.app_context():
        from app import models
        assert models.get_booking(b)["status"] == "requested"  # refused


# ---------- admin add booking ----------

def test_admin_add_booking(app, client):
    _login(client)
    with app.app_context():
        from app import models
        iid = models.create_item("Kayak", "kayak", "", 8, "day", 0)
    client.post("/admin/bookings/new", data={
        "item_id": str(iid), "renter_name": "Sam", "status": "confirmed",
        "start_date": "2098-10-01", "end_date": "2098-10-03"})
    with app.app_context():
        from app import models
        bs, _ = models.list_bookings()
    assert any(b["renter_name"] == "Sam" and b["quoted_amount"] == 16.0 for b in bs)


# ---------- blackouts + agreement ----------

def test_blackout_blocks_request(app, client, stamp):
    with app.app_context():
        from app import models
        iid = models.create_item("Drill", "drill", "", 5, "day", 0)
        models.create_blackout(iid, "2098-11-10", "2098-11-15", "maint")
    client.post("/item/drill", data={"renter_name": "Sam", "agree": "1",
                "renter_email": "sam@example.com", "form_stamp": stamp(),
                "start_date": "2098-11-12", "end_date": "2098-11-14"}, follow_redirects=True)
    with app.app_context():
        from app import models
        bookings, _ = models.list_bookings()
        assert bookings == []  # blocked


def test_agreement_required(app, client, stamp):
    with app.app_context():
        from app import models
        models.create_item("Canoe", "canoe", "", 5, "day", 0)
    client.post("/item/canoe", data={"renter_name": "Sam",  # no 'agree'
                "renter_email": "sam@example.com", "form_stamp": stamp(),
                "start_date": "2098-12-01", "end_date": "2098-12-03"}, follow_redirects=True)
    with app.app_context():
        from app import models
        assert models.list_bookings()[0] == []


# ---------- settings + email ----------

def test_settings_saved(app, client):
    _login(client)
    client.post("/admin/settings", data={
        "admin_email": "me@x.com", "agreement_text": "be nice", "notify_on_request": "1"})
    with app.app_context():
        from app import models
        assert models.get_setting("admin_email") == "me@x.com"
        assert models.get_setting("notify_on_confirm") == "0"   # unchecked -> off
        assert models.get_setting("agreement_text") == "be nice"


def test_request_sends_emails(app, client, monkeypatch, stamp):
    sent = []
    import app.mail as mailmod
    monkeypatch.setattr(mailmod, "send_email",
                        lambda to, subj, text: sent.append(to) or True)
    with app.app_context():
        from app import models
        models.create_item("Speaker", "speaker", "", 5, "day", 0)
        models.set_setting("admin_email", "admin@x.com")
    client.post("/item/speaker", data={
        "form_stamp": stamp(),
        "renter_name": "Sam", "renter_email": "sam@x.com", "agree": "1",
        "start_date": "2099-01-01", "end_date": "2099-01-03"}, follow_redirects=True)
    assert "admin@x.com" in sent and "sam@x.com" in sent


# ---- health ----------------------------------------------------------------

def test_healthz_reports_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


# ---- bad numeric input should be a message, not a 500 ----------------------

def test_bad_rate_is_rejected_not_500(app, client):
    _login(client)
    resp = client.post("/admin/items/new", data={
        "name": "Nonsense Rate", "rate_amount": "ten bucks",
        "rate_unit": "day", "deposit_amount": "0",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Rate must be a number" in resp.data
    with app.app_context():
        from app import models
        assert models.get_item_by_slug("nonsense-rate") is None


def test_negative_deposit_is_rejected(app, client):
    _login(client)
    resp = client.post("/admin/items/new", data={
        "name": "Negative Deposit", "rate_amount": "5",
        "rate_unit": "day", "deposit_amount": "-20",
    }, follow_redirects=True)
    assert b"Deposit must be a number" in resp.data
    with app.app_context():
        from app import models
        assert models.get_item_by_slug("negative-deposit") is None


def test_unknown_rate_unit_is_rejected(app, client):
    """quote_amount raises on an unknown unit, so a bad unit must never persist."""
    _login(client)
    resp = client.post("/admin/items/new", data={
        "name": "Bad Unit", "rate_amount": "5",
        "rate_unit": "fortnight", "deposit_amount": "0",
    }, follow_redirects=True)
    assert b"Rate unit must be" in resp.data
    with app.app_context():
        from app import models
        assert models.get_item_by_slug("bad-unit") is None


def test_money_field_tolerates_currency_formatting(app, client):
    _login(client)
    client.post("/admin/items/new", data={
        "name": "Formatted", "rate_amount": "$1,250.50",
        "rate_unit": "flat", "deposit_amount": "",
    }, follow_redirects=True)
    with app.app_context():
        from app import models
        item = models.get_item_by_slug("formatted")
        assert item["rate_amount"] == 1250.50
        assert item["deposit_amount"] == 0


# ---- item delete, guarded by rental history --------------------------------

def test_item_delete_when_unbooked(app, client):
    _login(client)
    with app.app_context():
        from app import models
        item_id = models.create_item("Spare Ladder", "spare-ladder", "", 5, "day", 0)
        models.create_blackout(item_id, "2098-09-01", "2098-09-03", "paint")

    client.post(f"/admin/items/{item_id}/delete", follow_redirects=True)

    with app.app_context():
        from app import models
        assert models.get_item(item_id) is None
        assert models.list_blackouts(item_id) == []   # blackouts cascade


def test_item_delete_blocked_by_booking(app, client):
    _login(client)
    with app.app_context():
        from app import models
        item_id = models.create_item("Booked Trailer", "booked-trailer", "", 5, "day", 0)
        models.create_booking(item_id, "Sam", "", "2098-09-01", "2098-09-04", 15, 0)

    resp = client.post(f"/admin/items/{item_id}/delete", follow_redirects=True)
    assert b"Hide it instead" in resp.data

    with app.app_context():
        from app import models
        assert models.get_item(item_id) is not None


def test_item_delete_requires_login(app, client):
    with app.app_context():
        from app import models
        item_id = models.create_item("Unguarded", "unguarded", "", 5, "day", 0)

    resp = client.post(f"/admin/items/{item_id}/delete")
    assert resp.status_code in (301, 302)

    with app.app_context():
        from app import models
        assert models.get_item(item_id) is not None


def test_delete_button_hidden_for_booked_items(app, client):
    _login(client)
    with app.app_context():
        from app import models
        free_id = models.create_item("Free Item", "free-item", "", 5, "day", 0)
        booked_id = models.create_item("Booked Item", "booked-item", "", 5, "day", 0)
        models.create_booking(booked_id, "Sam", "", "2098-09-01", "2098-09-04", 15, 0)

    body = client.get("/admin/items").data.decode()
    assert f"/admin/items/{free_id}/delete" in body
    assert f"/admin/items/{booked_id}/delete" not in body


# ---- uploaded photos are cleaned up ----------------------------------------

def _age_uploads(app, seconds=3600):
    """Backdate every upload so prune_uploads stops treating them as in-flight."""
    import os, time
    upload_dir = app.config["UPLOAD_DIR"]
    old = time.time() - seconds
    for name in os.listdir(upload_dir):
        os.utime(os.path.join(upload_dir, name), (old, old))


def _fake_upload(app, name="deadbeef.webp"):
    """Drop a file in the upload dir and return its stored photo_path."""
    import os
    upload_dir = app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, name), "wb") as fh:
        fh.write(b"not really a webp")
    return "uploads/" + name


def test_replacing_a_photo_deletes_the_old_upload(app, client):
    import os
    _login(client)
    with app.app_context():
        from app import models
        old = _fake_upload(app, "old-photo.webp")
        item_id = models.create_item("Photo Swap", "photo-swap", "", 5, "day", 0,
                                     photo_path=old)

    client.post(f"/admin/items/{item_id}/edit", data={
        "name": "Photo Swap", "rate_amount": "5", "rate_unit": "day",
        "deposit_amount": "0", "default_image": "img/defaults/03.svg",
    }, follow_redirects=True)

    with app.app_context():
        from app import models
        assert models.get_item(item_id)["photo_path"] == "img/defaults/03.svg"
    assert not os.path.exists(os.path.join(app.config["UPLOAD_DIR"], "old-photo.webp"))


def test_editing_without_touching_the_photo_keeps_the_file(app, client):
    import os
    _login(client)
    with app.app_context():
        from app import models
        kept = _fake_upload(app, "kept-photo.webp")
        item_id = models.create_item("Keep Photo", "keep-photo", "", 5, "day", 0,
                                     photo_path=kept)

    client.post(f"/admin/items/{item_id}/edit", data={
        "name": "Keep Photo Renamed", "rate_amount": "7", "rate_unit": "day",
        "deposit_amount": "0",
    }, follow_redirects=True)

    assert os.path.exists(os.path.join(app.config["UPLOAD_DIR"], "kept-photo.webp"))
    with app.app_context():
        from app import models
        assert models.get_item(item_id)["photo_path"] == kept


def test_deleting_an_item_deletes_its_upload(app, client):
    import os
    _login(client)
    with app.app_context():
        from app import models
        photo = _fake_upload(app, "doomed-photo.webp")
        item_id = models.create_item("Doomed", "doomed", "", 5, "day", 0,
                                     photo_path=photo)

    client.post(f"/admin/items/{item_id}/delete", follow_redirects=True)
    assert not os.path.exists(os.path.join(app.config["UPLOAD_DIR"], "doomed-photo.webp"))


def test_discard_upload_never_touches_bundled_defaults(app):
    """Plants a decoy named like a default *inside* UPLOAD_DIR, so this fails if
    the 'uploads/' prefix guard is ever removed. Asserting only the return value
    would pass either way, since basename() would just miss a nonexistent file."""
    import os
    from app.photos import discard_upload
    with app.app_context():
        upload_dir = app.config["UPLOAD_DIR"]
        os.makedirs(upload_dir, exist_ok=True)
        decoy = os.path.join(upload_dir, "03.svg")
        with open(decoy, "w") as fh:
            fh.write("<svg/>")

        assert discard_upload("img/defaults/03.svg") is False
        assert os.path.exists(decoy), "prefix guard gone: a default was deleted"
        assert discard_upload(None) is False
        assert discard_upload("") is False


def test_discard_upload_cannot_escape_the_upload_dir(app):
    """A crafted path must not reach outside UPLOAD_DIR."""
    import os
    from app.photos import discard_upload
    with app.app_context():
        outside = os.path.join(app.config["UPLOAD_DIR"], "..", "hands-off.txt")
        with open(outside, "w") as fh:
            fh.write("keep me")
        assert discard_upload("uploads/../hands-off.txt") is False
        assert os.path.exists(outside)
        os.unlink(outside)


def test_prune_uploads_removes_only_unreferenced_files(app):
    import os
    from app.photos import prune_uploads
    with app.app_context():
        from app import models
        live = _fake_upload(app, "live.webp")
        _fake_upload(app, "orphan-a.webp")
        _fake_upload(app, "orphan-b.webp")
        models.create_item("Live", "live", "", 5, "day", 0, photo_path=live)
        models.create_item("Default Art", "default-art", "", 5, "day", 0,
                           photo_path="img/defaults/01.svg")

        _age_uploads(app)   # past the in-flight grace window
        assert prune_uploads(dry_run=True) == ["orphan-a.webp", "orphan-b.webp"]
        assert os.path.exists(os.path.join(app.config["UPLOAD_DIR"], "orphan-a.webp"))

        assert prune_uploads() == ["orphan-a.webp", "orphan-b.webp"]
        upload_dir = app.config["UPLOAD_DIR"]
        assert not os.path.exists(os.path.join(upload_dir, "orphan-a.webp"))
        assert not os.path.exists(os.path.join(upload_dir, "orphan-b.webp"))
        assert os.path.exists(os.path.join(upload_dir, "live.webp"))


def test_prune_uploads_spares_in_flight_files(app):
    """A file written seconds ago may belong to a row that hasn't committed yet."""
    import os
    from app.photos import prune_uploads
    with app.app_context():
        _fake_upload(app, "just-written.webp")
        assert prune_uploads(dry_run=True) == []
        assert os.path.exists(os.path.join(app.config["UPLOAD_DIR"], "just-written.webp"))


# ---- regressions -----------------------------------------------------------

def test_dashboard_renders_with_bookings(app, client):
    """outstanding_by_renter reads sqlite3.Row, which is neither a dict nor
    attribute-accessible — the old _field() raised AttributeError, so the
    dashboard 500'd as soon as a single booking existed."""
    _login(client)
    with app.app_context():
        from app import models
        item_id = models.create_item("Dash Rig", "dash-rig", "", 10, "day", 0)
        models.create_booking(item_id, "Sam", "", "2098-09-01", "2098-09-04", 30, 0)
        models.create_booking(item_id, "Ada", "", "2098-09-10", "2098-09-12", 20, 0)

    resp = client.get("/admin/")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Sam" in body and "Ada" in body


def test_outstanding_by_renter_accepts_sqlite_rows(app):
    from app.availability import outstanding_by_renter
    with app.app_context():
        from app import models
        item_id = models.create_item("Rollup Rig", "rollup-rig", "", 10, "day", 0)
        models.create_booking(item_id, "Sam", "", "2098-09-01", "2098-09-04", 30, 0)
        rows, _ = models.list_bookings()
        assert outstanding_by_renter(rows) == {"Sam": 30.0}


import pytest


@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_non_finite_money_is_rejected(app, client, bad):
    """float() parses these. NaN passes `< 0` and then hits a REAL NOT NULL
    column as NULL (IntegrityError -> 500); inf stores fine and poisons every
    quote and rollup downstream, forever."""
    _login(client)
    resp = client.post("/admin/items/new", data={
        "name": f"Bad {bad}", "rate_amount": bad,
        "rate_unit": "day", "deposit_amount": "0",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Rate must be a number" in resp.data
    with app.app_context():
        from app import models
        assert all(i["name"] != f"Bad {bad}" for i in models.list_items())


def test_non_finite_paid_amount_is_rejected(app, client):
    _login(client)
    with app.app_context():
        from app import models
        item_id = models.create_item("Paid Rig", "paid-rig", "", 10, "day", 0)
        bid = models.create_booking(item_id, "Sam", "", "2098-09-01", "2098-09-04", 30, 0)

    resp = client.post(f"/admin/bookings/{bid}/paid", data={"paid_amount": "nan"},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        from app import models
        assert not models.get_booking(bid)["is_paid"]


def test_delete_guard_is_atomic_not_check_then_delete(app):
    """booking.item_id is ON DELETE CASCADE, so a check-then-delete pair lets a
    booking that commits in the gap get silently cascaded away. The guard must
    live in the DELETE itself."""
    with app.app_context():
        from app import models
        item_id = models.create_item("Racy", "racy", "", 5, "day", 0)
        models.create_booking(item_id, "Sam", "", "2098-09-01", "2098-09-04", 15, 0)

        assert models.delete_item_if_unbooked(item_id) is False
        assert models.get_item(item_id) is not None
        assert models.count_bookings_for_item(item_id) == 1   # history intact


def test_healthz_fails_when_the_schema_is_missing(app):
    """A vanished volume leaves sqlite3.connect() creating an empty file, which
    answers SELECT 1 happily — the probe has to touch a real table."""
    import os, tempfile
    from app.config import Config
    from app import create_app

    empty = os.path.join(tempfile.mkdtemp(), "gone.sqlite3")

    class Broken(Config):
        TESTING = True
        DATABASE = empty
        SECRET_KEY = "test"
        WTF_CSRF_ENABLED = False
        UPLOAD_DIR = tempfile.mkdtemp()

    resp = create_app(Broken).test_client().get("/healthz")   # never init-db'd
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "error"


# =========================================================================== #
# Hardening (spec categories 1-6), ported from FreeStuff plus Category 4
# =========================================================================== #
import json

import pytest

from app import hardening, limits


def _item(app, name="Trailer", slug="trailer"):
    with app.app_context():
        from app import models
        return models.create_item(name, slug, "", 10, "day", 0)


def _bookings(app):
    with app.app_context():
        from app import models
        rows, _ = models.list_bookings()
        return rows


# ---------- Category 4: the email relay, RentStuff's own vector -------------

@pytest.fixture
def outbox(app, monkeypatch):
    """Capture what actually reaches the mail transport.

    Mail has to be *configured* for this to mean anything: with no MAILGUN_*
    env, send_email returns False for every address, so asserting on the return
    value alone would pass whether or not the recipient was ever validated.
    That mistake is what this fixture exists to prevent — the assertions below
    are about which addresses reached urlopen, not what send_email returned.
    """
    sent = []
    monkeypatch.setenv("MAILGUN_API_KEY", "test-key")
    monkeypatch.setenv("MAILGUN_DOMAIN", "test.example")

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        from urllib.parse import parse_qs
        sent.append(parse_qs(req.data.decode())["to"][0])
        return _Resp()

    from app import mail
    monkeypatch.setattr(mail.urllib.request, "urlopen", fake_urlopen)
    return sent


def test_send_email_refuses_a_malformed_recipient(app, outbox):
    """The reserve form is a machine that mails an address a stranger typed.

    Left open, anyone can put a victim's address in the form and have our
    domain and our Mailgun account deliver to them.
    """
    with app.app_context():
        from app import mail
        assert mail.send_email("real@example.com", "s", "t") is True
        for bad in ("not-an-address", "a@b.com\r\nBcc: victim@x.com",
                    "a@b.com, victim@x.com", "<victim@x.com>", "a@@b.com"):
            assert mail.send_email(bad, "s", "t") is False
    # Only the one good address was ever handed to the transport.
    assert outbox == ["real@example.com"]


def test_mail_budget_caps_what_one_address_can_be_sent(app, outbox, monkeypatch):
    """Stops a flood of *mail*, which isn't the same thing as a flood of bookings.

    An attacker spreading submissions across IPs to dodge the form rate limiter
    would otherwise still get us to mail their victim over and over.
    """
    monkeypatch.setattr(limits, "mail_budget",
                        hardening.NotificationBudget(limit=3))
    with app.app_context():
        from app import mail
        results = [mail.send_email("victim@example.com", "s", "t")
                   for _ in range(6)]
    assert results == [True, True, True, False, False, False]
    assert len(outbox) == 3, "budget must stop sends before the transport"


def test_mail_budget_does_not_penalise_other_recipients(app, outbox, monkeypatch):
    monkeypatch.setattr(limits, "mail_budget",
                        hardening.NotificationBudget(limit=2))
    with app.app_context():
        from app import mail
        for _ in range(4):
            mail.send_email("victim@example.com", "s", "t")
        assert mail.send_email("admin@example.com", "s", "t") is True
    assert outbox.count("victim@example.com") == 2
    assert outbox.count("admin@example.com") == 1


def test_booking_notifications_go_through_the_same_guards(app, reserve, outbox):
    """The guards live in send_email, so no notification path can skip them."""
    _item(app)
    with app.app_context():
        from app import models
        models.set_setting("admin_email", "owner@example.com")
    reserve("trailer", renter_email="renter@example.com",
            start_date="2098-09-01", end_date="2098-09-03")
    assert sorted(outbox) == ["owner@example.com", "renter@example.com"]


def test_mail_budget_is_per_address(app):
    budget = hardening.NotificationBudget(limit=2)
    assert [budget.allow("a@x.com") for _ in range(3)] == [True, True, False]
    assert budget.allow("b@x.com") is True          # unrelated address unaffected
    assert budget.allow("A@X.com ") is False        # same address, different case


def test_booking_with_a_bad_email_is_rejected_before_it_is_stored(app, reserve):
    _item(app)
    reserve("trailer", renter_email="victim@example.com\nbcc: evil@x.com",
            start_date="2098-09-01", end_date="2098-09-03")
    assert _bookings(app) == []


def test_disposable_email_rejected_only_when_enabled(app, reserve):
    _item(app)
    reserve("trailer", renter_email="throwaway@mailinator.com",
            start_date="2098-09-01", end_date="2098-09-03")
    assert len(_bookings(app)) == 1                  # off by default
    app.config["BLOCK_DISPOSABLE_EMAIL"] = True
    _item(app, "Van", "van")
    reserve("van", renter_email="throwaway@mailinator.com",
            start_date="2098-09-01", end_date="2098-09-03")
    assert len(_bookings(app)) == 1                  # still 1 — the van was refused


# ---------- Category 1: origin & intent ------------------------------------

def test_reserve_form_serves_a_stamp_and_honeypots(app, client):
    _item(app)
    page = client.get("/item/trailer").get_data(as_text=True)
    assert 'name="form_stamp"' in page
    for f in hardening.HONEYPOT_FIELDS:
        assert f'name="{f}"' in page
    assert 'tabindex="-1"' in page and 'aria-hidden="true"' in page


def test_direct_post_without_a_stamp_is_rejected(app, client):
    """The attack's actual shape: a POST that never loaded the page."""
    _item(app)
    client.post("/item/trailer", data={
        "renter_name": "vhnnhidmrs", "renter_contact": "tyoyiosrzf",
        "renter_email": "jewflgkv@immenseignite.info", "agree": "1",
        "start_date": "2098-09-01", "end_date": "2098-09-03"},
        follow_redirects=True)
    assert _bookings(app) == []


def test_instant_submission_is_rejected(app, reserve, stamp):
    _item(app)
    r = reserve("trailer", form_stamp=stamp(seconds_ago=0),
                start_date="2098-09-01", end_date="2098-09-03")
    assert _bookings(app) == []
    # Vague on purpose — naming the control is free tuning feedback for a prober.
    assert b"honeypot" not in r.data.lower() and b"too fast" not in r.data.lower()


def test_stale_form_gets_a_helpful_message(app, reserve, stamp):
    """Someone who left the tab open overnight is not an attacker."""
    _item(app)
    r = reserve("trailer", form_stamp=stamp(seconds_ago=60 * 60 * 24),
                start_date="2098-09-01", end_date="2098-09-03")
    assert b"went stale" in r.data


def test_honeypot_blocks_a_bot_that_fills_everything(app, reserve):
    _item(app)
    reserve("trailer", website="http://spam.example",
            start_date="2098-09-01", end_date="2098-09-03")
    assert _bookings(app) == []


# ---------- Category 2: rate limiting --------------------------------------

def test_reserve_flood_is_rate_limited(app, reserve):
    """Replays the August 18 attack: 21 requests, back to back."""
    for i, slug in enumerate(("a", "b", "c")):
        _item(app, f"Item {i}", slug)
    for i in range(21):
        reserve(("a", "b", "c")[i % 3], renter_email=f"bot{i}@example.com",
                start_date="2098-09-01", end_date="2098-09-03")
    assert len(_bookings(app)) == limits.RATE_LIMITS["reserve_burst"][0]


def test_per_item_limit_stops_one_item_being_swamped(app, reserve):
    _item(app)
    for i in range(3):
        reserve("trailer", renter_email=f"p{i}@example.com",
                start_date=f"2098-09-0{i+1}", end_date=f"2098-09-0{i+2}")
    assert len(_bookings(app)) == limits.RATE_LIMITS["reserve_item"][0]


def test_rate_limit_is_logged_with_the_offending_ip(app, reserve, capsys):
    _item(app)
    for i in range(5):
        reserve("trailer", renter_email=f"p{i}@example.com",
                start_date=f"2098-09-0{i+1}", end_date=f"2098-09-0{i+2}")
    events = [json.loads(l) for l in capsys.readouterr().out.splitlines()
              if l.startswith("{")]
    limited = [e for e in events if e["event"] == "rate_limited"]
    assert limited and limited[0]["retry_after"] > 0
    assert all(e["app"] == "rentstuff" for e in events)   # family log format


def test_logs_never_contain_renter_details(app, reserve, capsys):
    _item(app)
    reserve("trailer", renter_name="Sam Secret", renter_email="sam@private.example",
            renter_contact="555-867-5309", notes="my address is 12 Elm St",
            start_date="2098-09-01", end_date="2098-09-03")
    out = capsys.readouterr().out
    for secret in ("Sam Secret", "sam@private.example", "867-5309", "12 Elm St"):
        assert secret not in out, secret


# ---------- Category 3: input validation -----------------------------------

def test_gibberish_booking_from_the_attack_is_rejected(app, reserve):
    """The literal payload from the August 18 flood."""
    _item(app)
    reserve("trailer", renter_name="vhnnhidmrs", renter_contact="tyoyiosrzf",
            renter_email="", start_date="2098-09-01", end_date="2098-09-03")
    assert _bookings(app) == []


def test_a_booking_needs_at_least_one_way_to_reach_you(app, reserve):
    """Email and phone are each optional, but not both — the form's own rule."""
    _item(app)
    reserve("trailer", renter_email="", renter_contact="",
            start_date="2098-09-01", end_date="2098-09-03")
    assert _bookings(app) == []


def test_phone_only_booking_is_accepted(app, reserve):
    """Email is optional here; a phone number alone must still work."""
    _item(app)
    reserve("trailer", renter_email="", renter_contact="(555) 123-4567",
            start_date="2098-09-01", end_date="2098-09-03")
    assert len(_bookings(app)) == 1


def test_past_dates_are_rejected_server_side(app, reserve):
    """min= on the input is a client-side hint; a direct POST ignores it.

    A booking in the past is invisible to every availability check, so it can
    never conflict and never expires out of the dashboard.
    """
    _item(app)
    reserve("trailer", start_date="2020-01-01", end_date="2020-01-03")
    assert _bookings(app) == []


def test_absurdly_long_rental_is_rejected(app, reserve):
    """One POST could otherwise take an item off the calendar for years."""
    _item(app)
    reserve("trailer", start_date="2098-09-01", end_date="2099-09-01")
    assert _bookings(app) == []


def test_duplicate_request_for_the_same_window_is_absorbed(app, reserve):
    _item(app)
    reserve("trailer", renter_email="sam@example.com",
            start_date="2098-09-01", end_date="2098-09-03")
    r = reserve("trailer", renter_email="SAM@example.com ",
                start_date="2098-09-01", end_date="2098-09-03")
    assert len(_bookings(app)) == 1
    assert b"already requested" in r.data


def test_different_dates_are_not_a_duplicate(app, reserve):
    """Same person, different window, is a real second booking."""
    _item(app)
    reserve("trailer", renter_email="sam@example.com",
            start_date="2098-09-01", end_date="2098-09-03")
    reserve("trailer", renter_email="sam@example.com",
            start_date="2098-10-01", end_date="2098-10-03")
    assert len(_bookings(app)) == 2


def test_a_normal_booking_still_sails_through(app, reserve):
    """False-positive guard: none of the above may block a real renter."""
    _item(app)
    r = reserve("trailer",
                renter_name="Ana O'Brien-Szczepanski",
                renter_email="ana.obrien+rent@example.co.uk",
                renter_contact="+1 (555) 123-4567",
                notes="Thanks! Picking up after 5 — see http://example.com/map",
                start_date="2098-09-01", end_date="2098-09-04")
    assert r.status_code == 200
    assert len(_bookings(app)) == 1


# ---------- admin auth ------------------------------------------------------

def test_login_next_cannot_redirect_off_site(app):
    """`next` was previously used unfiltered — a ready-made phishing hop."""
    from app.auth import safe_next
    hostile = ("https://evil.example/x", "//evil.example/x",
               "http://evil.example", "javascript:alert(1)", "")
    with app.test_request_context():
        for target in hostile:
            assert safe_next(target) == "/admin/"
        # ...and the legitimate case still works.
        assert safe_next("/admin/items") == "/admin/items"


def test_login_is_rate_limited(client):
    limit = limits.RATE_LIMITS["login_failed"][0]
    for _ in range(limit):
        r = client.post("/login", data={"username": "admin", "password": "no"})
        assert r.status_code == 200
    r = client.post("/login", data={"username": "admin", "password": "no"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_successful_login_clears_the_failure_counter(client, app):
    """A typo or two must not leave a real admin near the lockout threshold."""
    import os
    from werkzeug.security import generate_password_hash
    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash("right-password")
    for _ in range(3):
        client.post("/login", data={"username": "admin", "password": "no"})
    r = client.post("/login", data={"username": "admin", "password": "right-password"})
    assert r.status_code == 302
    for _ in range(4):   # would trip the limit if the counter had persisted
        r = client.post("/login", data={"username": "admin", "password": "no"})
    assert r.status_code == 200


def test_logout_is_post_only(client):
    """As a GET this was drive-by triggerable with <img src="/logout">."""
    with client.session_transaction() as sess:
        sess["is_admin"] = True
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code in (301, 302)
    with client.session_transaction() as sess:
        assert "is_admin" not in sess


# ---------- headers ---------------------------------------------------------

def test_security_headers_are_present(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in r.headers


def test_uploaded_media_is_served_sandboxed(app, client):
    import io
    from PIL import Image
    with client.session_transaction() as sess:
        sess["is_admin"] = True
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(buf, "PNG")
    buf.seek(0)
    client.post("/admin/items/new", data={
        "name": "Ladder", "rate_amount": "4", "rate_unit": "day",
        "deposit_amount": "0", "photo": (buf, "l.png")},
        content_type="multipart/form-data")
    with app.app_context():
        from app import models
        path = models.get_item_by_slug("ladder")["photo_path"]
    csp = client.get("/media/" + path.split("/", 1)[1]).headers.get(
        "Content-Security-Policy", "")
    assert "sandbox" in csp and "default-src 'none'" in csp


def test_upload_rejects_a_decompression_bomb(app, client):
    """Image.open is lazy; convert() is what allocates. Check before decoding."""
    import io
    from PIL import Image
    app.config["MAX_IMAGE_PIXELS"] = 100
    with client.session_transaction() as sess:
        sess["is_admin"] = True
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, "PNG")   # 4096 px > 100
    buf.seek(0)
    client.post("/admin/items/new", data={
        "name": "Huge", "rate_amount": "4", "rate_unit": "day",
        "deposit_amount": "0", "photo": (buf, "big.png")},
        content_type="multipart/form-data")
    with app.app_context():
        from app import models
        item = models.get_item_by_slug("huge")
    assert not item["photo_path"], "oversized image should not have been stored"
