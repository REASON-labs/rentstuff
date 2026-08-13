import functools

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

bp = Blueprint("auth", __name__)


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        ok = (
            username == current_app.config["ADMIN_USERNAME"]
            and check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], password)
        )
        if ok:
            session.clear()
            session["is_admin"] = True
            nxt = request.args.get("next") or url_for("admin.dashboard")
            return redirect(nxt)
        flash("Wrong username or password.")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("public.index"))
