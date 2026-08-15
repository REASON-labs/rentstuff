"""A couple of smoke tests to prove the app wires together."""


def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_admin_requires_login(client):
    # unauthenticated admin should redirect to login
    resp = client.get("/admin/")
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers["Location"]


def test_request_flow_creates_booking(app, client):
    from app import models
    with app.app_context():
        item_id = models.create_item("Test Truck", "test-truck", "", 10, "day", 0)

    resp = client.post("/item/test-truck", data={
        "renter_name": "Sam",
        "renter_contact": "sam@example.com",
        "agree": "1",
        "start_date": "2026-09-01",
        "end_date": "2026-09-04",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        from app import models
        bookings = models.list_bookings()
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
                              start_date="2026-09-01", end_date="2026-09-05",
                              quoted_amount=40, deposit_amount=0, status="confirmed")
        b = models.create_booking(item_id=iid, renter_name="B", renter_contact="",
                                  start_date="2026-09-03", end_date="2026-09-07",
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
        "start_date": "2026-10-01", "end_date": "2026-10-03"})
    with app.app_context():
        from app import models
        bs = models.list_bookings()
    assert any(b["renter_name"] == "Sam" and b["quoted_amount"] == 16.0 for b in bs)


# ---------- blackouts + agreement ----------

def test_blackout_blocks_request(app, client):
    with app.app_context():
        from app import models
        iid = models.create_item("Drill", "drill", "", 5, "day", 0)
        models.create_blackout(iid, "2026-11-10", "2026-11-15", "maint")
    client.post("/item/drill", data={"renter_name": "Sam", "agree": "1",
                "start_date": "2026-11-12", "end_date": "2026-11-14"}, follow_redirects=True)
    with app.app_context():
        from app import models
        assert models.list_bookings() == []  # blocked


def test_agreement_required(app, client):
    with app.app_context():
        from app import models
        models.create_item("Canoe", "canoe", "", 5, "day", 0)
    client.post("/item/canoe", data={"renter_name": "Sam",  # no 'agree'
                "start_date": "2026-12-01", "end_date": "2026-12-03"}, follow_redirects=True)
    with app.app_context():
        from app import models
        assert models.list_bookings() == []


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


def test_request_sends_emails(app, client, monkeypatch):
    sent = []
    import app.mail as mailmod
    monkeypatch.setattr(mailmod, "send_email",
                        lambda to, subj, text: sent.append(to) or True)
    with app.app_context():
        from app import models
        models.create_item("Speaker", "speaker", "", 5, "day", 0)
        models.set_setting("admin_email", "admin@x.com")
    client.post("/item/speaker", data={
        "renter_name": "Sam", "renter_email": "sam@x.com", "agree": "1",
        "start_date": "2027-01-01", "end_date": "2027-01-03"}, follow_redirects=True)
    assert "admin@x.com" in sent and "sam@x.com" in sent
