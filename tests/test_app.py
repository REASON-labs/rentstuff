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
