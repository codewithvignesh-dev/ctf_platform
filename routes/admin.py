import os
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    send_file, current_app, jsonify
)
from flask_login import login_required, current_user

from models import (
    db, User, Category, Challenge, MCQQuestion, MCQOption,
    Setting, AntiCheatLog, Submission
)
from utils.decorators import role_required
from utils.excel_import import import_students_from_excel, build_credentials_workbook

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/dashboard")
@login_required
@role_required("admin")
def dashboard():
    stats = {
        "students": User.query.filter_by(role="student").count(),
        "staff": User.query.filter_by(role="staff").count(),
        "challenges": Challenge.query.count(),
        "categories": Category.query.count(),
        "blocked": User.query.filter_by(is_blocked=True).count(),
    }
    event_status = Setting.get("event_status", "waiting")
    return render_template("admin/dashboard.html", stats=stats, event_status=event_status)


# ---------------------------------------------------------------------------
# Event control: waiting -> live -> paused -> resumed -> ended
# ---------------------------------------------------------------------------
@admin_bp.route("/event/set-status", methods=["POST"])
@login_required
@role_required("admin")
def set_event_status():
    new_status = request.form.get("status")
    if new_status in ("waiting", "live", "paused", "ended"):
        Setting.set("event_status", new_status)
        flash(f"Event status changed to: {new_status.upper()}", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def settings():
    if request.method == "POST":
        Setting.set("chat_enabled", "1" if request.form.get("chat_enabled") == "on" else "0")
        Setting.set("mcq_result_video_url", request.form.get("mcq_result_video_url", "").strip())
        Setting.set("mcq_bgm_url", request.form.get("mcq_bgm_url", "").strip())
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    current_settings = {
        "chat_enabled": Setting.get("chat_enabled", "0") == "1",
        "mcq_result_video_url": Setting.get("mcq_result_video_url", ""),
        "mcq_bgm_url": Setting.get("mcq_bgm_url", ""),
    }
    return render_template("admin/settings.html", settings=current_settings)


# ---------------------------------------------------------------------------
# Categories (1st Year / 2nd Year / etc.)
# ---------------------------------------------------------------------------
@admin_bp.route("/categories", methods=["GET", "POST"])
@login_required
@role_required("admin")
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
            db.session.commit()
            flash(f"Category '{name}' created.", "success")
        return redirect(url_for("admin.categories"))

    all_categories = Category.query.all()
    return render_template("admin/categories.html", categories=all_categories)


@admin_bp.route("/categories/<int:category_id>/toggle-freeze", methods=["POST"])
@login_required
@role_required("admin")
def toggle_freeze(category_id):
    category = Category.query.get_or_404(category_id)
    category.scoreboard_frozen = not category.scoreboard_frozen
    db.session.commit()
    flash(f"Scoreboard for {category.name} is now {'FROZEN' if category.scoreboard_frozen else 'LIVE'}.", "success")
    return redirect(url_for("admin.categories"))


# ---------------------------------------------------------------------------
# Student bulk import via Excel (Name + Register Number -> auto credentials)
# ---------------------------------------------------------------------------
@admin_bp.route("/students", methods=["GET", "POST"])
@login_required
@role_required("admin")
def students():
    categories_list = Category.query.all()
    created_records = []
    skipped_rows = []

    if request.method == "POST":
        file = request.files.get("excel_file")
        default_category_id = request.form.get("category_id", type=int)

        if not file or file.filename == "":
            flash("Please choose an Excel file to upload.", "error")
        else:
            created_records, skipped_rows = import_students_from_excel(file, default_category_id)
            if created_records:
                # Stash the last batch in memory (session) for the download button
                from flask import session
                session["last_import_records"] = created_records
                flash(f"{len(created_records)} student accounts created.", "success")
            if skipped_rows:
                flash(f"{len(skipped_rows)} rows skipped - see details below.", "error")

    all_students = User.query.filter_by(role="student").order_by(User.name).all()
    return render_template(
        "admin/students.html",
        categories=categories_list,
        students=all_students,
        created_records=created_records,
        skipped_rows=skipped_rows,
    )


@admin_bp.route("/students/download-credentials")
@login_required
@role_required("admin")
def download_last_credentials():
    from flask import session
    records = session.get("last_import_records")
    if not records:
        flash("No recent import to download. Upload an Excel file first.", "error")
        return redirect(url_for("admin.students"))

    wb_buffer = build_credentials_workbook(records)
    return send_file(
        wb_buffer,
        as_attachment=True,
        download_name="student_credentials.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@admin_bp.route("/students/<int:user_id>/toggle-block", methods=["POST"])
@login_required
@role_required("admin")
def toggle_block(user_id):
    user = User.query.get_or_404(user_id)
    user.is_blocked = not user.is_blocked
    user.block_reason = "Manually blocked by admin" if user.is_blocked else None
    db.session.commit()
    flash(f"{user.name} is now {'BLOCKED' if user.is_blocked else 'UNBLOCKED'}.", "success")
    return redirect(url_for("admin.students"))


# ---------------------------------------------------------------------------
# Staff account creation (admin adds staff/invigilators)
# ---------------------------------------------------------------------------
@admin_bp.route("/staff", methods=["GET", "POST"])
@login_required
@role_required("admin")
def manage_staff():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username already exists.", "error")
        else:
            staff = User(username=username, name=name or username, role="staff")
            staff.set_password(password)
            db.session.add(staff)
            db.session.commit()
            flash(f"Staff account '{username}' created.", "success")
        return redirect(url_for("admin.manage_staff"))

    staff_list = User.query.filter_by(role="staff").all()
    return render_template("admin/staff.html", staff_list=staff_list)


# ---------------------------------------------------------------------------
# Challenges: CTF / MCQ / Debugging
# ---------------------------------------------------------------------------
@admin_bp.route("/challenges")
@login_required
@role_required("admin")
def challenges():
    all_challenges = Challenge.query.order_by(Challenge.created_at.desc()).all()
    return render_template("admin/challenges.html", challenges=all_challenges)


@admin_bp.route("/challenges/new/<ctype>", methods=["GET", "POST"])
@login_required
@role_required("admin")
def new_challenge(ctype):
    if ctype not in ("ctf", "mcq", "debug"):
        return "Unknown challenge type", 404

    categories_list = Category.query.all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        points = request.form.get("points", type=int, default=100)
        category_ids = request.form.getlist("category_ids")

        challenge = Challenge(title=title, description=description, type=ctype, points=points or 100)

        if ctype == "ctf":
            flag = request.form.get("flag", "").strip()
            challenge.set_flag(flag)

            file = request.files.get("attachment")
            if file and file.filename:
                ext = file.filename.rsplit(".", 1)[-1].lower()
                if ext in current_app.config["ALLOWED_ATTACHMENT_EXT"]:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
                    challenge.attachment_path = filename
                else:
                    flash("File type not allowed - challenge saved without attachment.", "error")

        elif ctype == "debug":
            challenge.buggy_code = request.form.get("buggy_code", "")
            challenge.expected_output = request.form.get("expected_output", "").strip()
            challenge.language = request.form.get("language", "").strip()

        elif ctype == "mcq":
            challenge.time_limit_seconds = request.form.get("time_limit_seconds", type=int, default=30)

        for cat_id in category_ids:
            cat = Category.query.get(int(cat_id))
            if cat:
                challenge.categories.append(cat)

        db.session.add(challenge)
        db.session.commit()

        if ctype == "mcq":
            flash("MCQ set created. Now add questions to it.", "success")
            return redirect(url_for("admin.mcq_questions", challenge_id=challenge.id))

        flash("Challenge created.", "success")
        return redirect(url_for("admin.challenges"))

    return render_template("admin/new_challenge.html", ctype=ctype, categories=categories_list)


@admin_bp.route("/challenges/<int:challenge_id>/toggle-active", methods=["POST"])
@login_required
@role_required("admin")
def toggle_challenge_active(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge.is_active = not challenge.is_active
    db.session.commit()
    return redirect(url_for("admin.challenges"))


@admin_bp.route("/challenges/<int:challenge_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    db.session.delete(challenge)
    db.session.commit()
    flash("Challenge deleted.", "success")
    return redirect(url_for("admin.challenges"))


@admin_bp.route("/challenges/<int:challenge_id>/questions", methods=["GET", "POST"])
@login_required
@role_required("admin")
def mcq_questions(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    if challenge.type != "mcq":
        return redirect(url_for("admin.challenges"))

    if request.method == "POST":
        question_text = request.form.get("question_text", "").strip()
        points = request.form.get("points", type=int, default=10)
        options = request.form.getlist("option_text")
        correct_index = request.form.get("correct_index", type=int)

        question = MCQQuestion(challenge_id=challenge.id, question_text=question_text, points=points or 10)
        db.session.add(question)
        db.session.flush()

        for i, opt_text in enumerate(options):
            if opt_text.strip():
                db.session.add(MCQOption(
                    question_id=question.id,
                    option_text=opt_text.strip(),
                    is_correct=(i == correct_index),
                ))

        db.session.commit()
        flash("Question added.", "success")
        return redirect(url_for("admin.mcq_questions", challenge_id=challenge.id))

    questions = MCQQuestion.query.filter_by(challenge_id=challenge.id).all()
    return render_template("admin/mcq_questions.html", challenge=challenge, questions=questions)


# ---------------------------------------------------------------------------
# Anti-cheat monitoring
# ---------------------------------------------------------------------------
@admin_bp.route("/anti-cheat")
@login_required
@role_required("admin")
def anti_cheat():
    logs = AntiCheatLog.query.order_by(AntiCheatLog.created_at.desc()).limit(300).all()
    blocked_users = User.query.filter_by(is_blocked=True).all()
    return render_template("admin/anti_cheat.html", logs=logs, blocked_users=blocked_users)
