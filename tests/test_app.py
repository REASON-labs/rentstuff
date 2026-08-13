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
