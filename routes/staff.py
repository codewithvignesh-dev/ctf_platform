from flask import Blueprint, render_template
from flask_login import login_required, current_user

from models import User, AntiCheatLog, Category, Setting, ChatMessage
from utils.decorators import role_required

staff_bp = Blueprint("staff", __name__)


@staff_bp.route("/dashboard")
@login_required
@role_required("staff", "admin")
def dashboard():
    students = User.query.filter_by(role="student").order_by(User.name).all()
    categories = Category.query.all()
    event_status = Setting.get("event_status", "waiting")
    return render_template(
        "staff/dashboard.html",
        students=students,
        categories=categories,
        event_status=event_status,
    )


@staff_bp.route("/violations")
@login_required
@role_required("staff", "admin")
def violations():
    logs = AntiCheatLog.query.order_by(AntiCheatLog.created_at.desc()).limit(200).all()
    return render_template("staff/violations.html", logs=logs)


@staff_bp.route("/chat")
@login_required
@role_required("staff", "admin")
def chat_monitor():
    messages = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(200).all()
    chat_enabled = Setting.get("chat_enabled", "0") == "1"
    return render_template("staff/chat_monitor.html", messages=messages, chat_enabled=chat_enabled)
