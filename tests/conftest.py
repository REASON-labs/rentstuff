import os
import tempfile
import time

import pytest

from app import create_app, limits
from app.config import Config
from app.db import init_db
from app.hardening import sign_form_stamp


@pytest.fixture
def app(tmp_path):
    fd, path = tempfile.mkstemp(suffix=".sqlite3")

    class TestConfig(Config):
        TESTING = True
        DATABASE = path
        SECRET_KEY = "test"
        WTF_CSRF_ENABLED = False
        ADMIN_USERNAME = "admin"
        # Per-test upload dir. Config derives UPLOAD_DIR from the *base*
        # DATABASE at import time, so without this override every test shares
        # one directory and they leak files into each other.
        UPLOAD_DIR = str(tmp_path / "uploads")

    # The rate limiter and mail budget are process-global, so without this a
    # test that submits four times would poison every test after it.
    limits.reset_for_tests()

    app = create_app(TestConfig)
    with app.app_context():
        init_db()
    yield app
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def stamp(app):
    """A validly-signed reserve-form stamp, aged to look like a human.

    Tests can't reuse the stamp the page renders: it's issued "now", and the
    server rejects anything submitted faster than MIN_FILL_SECONDS. Backdating
    one exercises the real signature path while standing in for the ten seconds
    a person would have spent filling the form in.
    """
    def make(seconds_ago=10):
        return sign_form_stamp(app.config["SECRET_KEY"],
                               issued_at=time.time() - seconds_ago)
    return make


@pytest.fixture
def reserve(client, stamp):
    """POST the reserve form with valid defaults; override any field."""
    def go(slug, **fields):
        data = {"renter_name": "Sam Taylor", "renter_email": "sam@example.com",
                "renter_contact": "", "notes": "", "agree": "1",
                "form_stamp": stamp()}
        data.update(fields)
        return client.post(f"/item/{slug}", data=data, follow_redirects=True)
    return go
