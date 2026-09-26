from datetime import datetime
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from models import db, Setting, AntiCheatLog, User, ChatMessage, Submission, Category
from config import Config
from utils.decorators import role_required

api_bp = Blueprint("api", __name__)


@api_bp.route("/event-status")
@login_required
def event_status():
    """Polled by the waiting room + student event page."""
    return jsonify({"status": Setting.get("event_status", "waiting")})


# ---------------------------------------------------------------------------
# Anti-cheat: student browser reports violations here
# ---------------------------------------------------------------------------
@api_bp.route("/anti-cheat/report", methods=["POST"])
@login_required
@role_required("student")
def report_violation():
    data = request.get_json(silent=True) or {}
    violation_type = data.get("type", "tab_switch")

    count = AntiCheatLog.query.filter_by(user_id=current_user.id, violation_type=violation_type).count() + 1

    db.session.add(AntiCheatLog(
        user_id=current_user.id, violation_type=violation_type, count_at_time=count
    ))

    total_violations = AntiCheatLog.query.filter_by(user_id=current_user.id).count() + 1
    blocked = False

    if total_violations >= Config.TAB_SWITCH_BLOCK_LIMIT:
        current_user.is_blocked = True
        current_user.block_reason = f"Anti-cheat: {violation_type} violation limit exceeded"
        blocked = True

    db.session.commit()

    return jsonify({
        "recorded": True,
        "total_violations": total_violations,
        "warn_limit": Config.TAB_SWITCH_WARN_LIMIT,
        "block_limit": Config.TAB_SWITCH_BLOCK_LIMIT,
        "blocked": blocked,
    })


# ---------------------------------------------------------------------------
# Staff / Admin live dashboard feed (polled every few seconds)
# ---------------------------------------------------------------------------
@api_bp.route("/live-feed")
@login_required
@role_required("staff", "admin")
def live_feed():
    students = User.query.filter_by(role="student").all()
    data = []
    for s in students:
        recent_violations = AntiCheatLog.query.filter_by(user_id=s.id).count()
        solved_count = Submission.query.filter_by(user_id=s.id, is_correct=True).count()
        data.append({
            "id": s.id,
            "name": s.name,
            "reg_number": s.reg_number,
            "category": s.category.name if s.category else "-",
            "score": s.total_score or 0,
            "solved": solved_count,
            "violations": recent_violations,
            "is_blocked": s.is_blocked,
        })
    return jsonify({"students": data, "event_status": Setting.get("event_status", "waiting")})


@api_bp.route("/scoreboard/<int:category_id>")
@login_required
def scoreboard_data(category_id):
    category = Category.query.get_or_404(category_id)
    if current_user.role == "student" and current_user.category_id != category_id:
        return jsonify({"error": "not authorized"}), 403

    students = (
        User.query.filter_by(role="student", category_id=category_id)
        .order_by(User.total_score.desc(), User.last_submission_at.asc())
        .all()
    )
    return jsonify({
        "frozen": category.scoreboard_frozen,
        "students": [
            {"rank": i + 1, "name": s.name, "reg_number": s.reg_number, "score": s.total_score or 0}
            for i, s in enumerate(students)
        ],
    })


# ---------------------------------------------------------------------------
# Simple event chat (admin can toggle on/off)
# ---------------------------------------------------------------------------
@api_bp.route("/chat/messages")
@login_required
def get_chat_messages():
    if Setting.get("chat_enabled", "0") != "1":
        return jsonify({"enabled": False, "messages": []})
    messages = ChatMessage.query.order_by(ChatMessage.created_at.desc()).limit(50).all()
    messages.reverse()
    return jsonify({
        "enabled": True,
        "messages": [
            {"user": m.user.name, "role": m.user.role, "message": m.message,
             "time": m.created_at.strftime("%H:%M:%S")}
            for m in messages
        ],
    })


@api_bp.route("/chat/send", methods=["POST"])
@login_required
def send_chat_message():
    if Setting.get("chat_enabled", "0") != "1":
        return jsonify({"error": "Chat is disabled"}), 403

    data = request.get_json(silent=True) or {}
    text = (data.get("message") or "").strip()
    if not text:
        return jsonify({"error": "Empty message"}), 400

    db.session.add(ChatMessage(user_id=current_user.id, message=text[:1000]))
    db.session.commit()
    return jsonify({"sent": True})
