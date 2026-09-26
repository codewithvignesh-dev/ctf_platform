from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/", methods=["GET"])
def index():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html")

        if user.is_blocked:
            flash(f"Your account has been blocked. Reason: {user.block_reason or 'Anti-cheat violation'}", "error")
            return render_template("auth/login.html")

        login_user(user)
        return _redirect_by_role(user)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


def _redirect_by_role(user):
    if user.is_admin():
        return redirect(url_for("admin.dashboard"))
    if user.is_staff():
        return redirect(url_for("staff.dashboard"))
    return redirect(url_for("student.waiting_room"))
