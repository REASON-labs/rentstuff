import os

from flask import Flask
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash

from . import db
from .config import Config

csrf = CSRFProtect()


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

    # Resolve an admin password hash if only a plaintext dev password was given.
    if not app.config.get("ADMIN_PASSWORD_HASH"):
        plaintext = os.environ.get("ADMIN_PASSWORD", "changeme")
        app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(plaintext)

    csrf.init_app(app)
    db.init_app(app)

    from . import auth
    from .routes import admin, public

    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp, url_prefix="/admin")

    @app.cli.command("init-db")
    def init_db_command():
        db.init_db()
        print("Initialized the database.")

    @app.cli.command("seed")
    def seed_command():
        from .seed import run
        run()
        print("Seeded sample data.")

    return app
