import os
import tempfile

import pytest

from app import create_app
from app.config import Config
from app.db import init_db


@pytest.fixture
def app():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")

    class TestConfig(Config):
        TESTING = True
        DATABASE = path
        SECRET_KEY = "test"
        WTF_CSRF_ENABLED = False
        ADMIN_USERNAME = "admin"

    app = create_app(TestConfig)
    with app.app_context():
        init_db()
    yield app
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()
