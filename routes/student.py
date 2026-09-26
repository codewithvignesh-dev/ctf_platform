import random
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user

from models import (
    db, Challenge, Submission, MCQQuestion, MCQOption, MCQAnswer,
    Category, User, Setting
)
from utils.decorators import role_required

student_bp = Blueprint("student", __name__)


@student_bp.route("/waiting-room")
@login_required
@role_required("student")
def waiting_room():
    status = Setting.get("event_status", "waiting")
    if status == "live":
        return redirect(url_for("student.event_home"))
    return render_template("student/waiting_room.html")


@student_bp.route("/")
@login_required
@role_required("student")
def event_home():
    status = Setting.get("event_status", "waiting")
    if status == "waiting":
        return redirect(url_for("student.waiting_room"))
    if status == "ended":
        return render_template("student/ended.html")

    challenges = []
    if current_user.category_id:
        category = Category.query.get(current_user.category_id)
        challenges = [c for c in category.challenges if c.is_active] if category else []

    solved_ids = {
        s.challenge_id for s in Submission.query.filter_by(user_id=current_user.id, is_correct=True)
    }
    return render_template(
        "student/event_home.html",
        challenges=challenges,
        solved_ids=solved_ids,
        event_status=status,
        chat_enabled=Setting.get("chat_enabled", "0") == "1",
    )


@student_bp.route("/challenge/<int:challenge_id>", methods=["GET", "POST"])
@login_required
@role_required("student")
def challenge_detail(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)

    allowed_category_ids = {c.id for c in challenge.categories}
    if current_user.category_id not in allowed_category_ids:
        return "Not authorized for this challenge.", 403

    already_solved = Submission.query.filter_by(
        user_id=current_user.id, challenge_id=challenge.id, is_correct=True
    ).first()

    result = None
    if request.method == "POST" and challenge.type in ("ctf", "debug"):
        answer = request.form.get("answer", "").strip()
        is_correct = False
        if challenge.type == "ctf":
            is_correct = challenge.check_flag(answer)
        elif challenge.type == "debug":
            expected = (challenge.expected_output or "").strip()
            is_correct = answer.strip() == expected

        existing = Submission.query.filter_by(user_id=current_user.id, challenge_id=challenge.id).first()
        if not existing or not existing.is_correct:
            points = challenge.points if is_correct else 0
            if existing:
                existing.answer_text = answer
                existing.is_correct = is_correct
                existing.points_awarded = points
            else:
                db.session.add(Submission(
                    user_id=current_user.id, challenge_id=challenge.id,
                    answer_text=answer, is_correct=is_correct, points_awarded=points,
                ))
            if is_correct:
                current_user.total_score = (current_user.total_score or 0) + points
                from datetime import datetime
                current_user.last_submission_at = datetime.utcnow()
            db.session.commit()
            result = "correct" if is_correct else "incorrect"
        else:
            result = "already_solved"

    return render_template(
        "student/challenge_detail.html",
        challenge=challenge,
        already_solved=already_solved,
        result=result,
    )


@student_bp.route("/challenge/<int:challenge_id>/download")
@login_required
@role_required("student")
def download_attachment(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    allowed_category_ids = {c.id for c in challenge.categories}
    if current_user.category_id not in allowed_category_ids or not challenge.attachment_path:
        return "Not authorized.", 403
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], challenge.attachment_path, as_attachment=True)


# ---------------------------------------------------------------------------
# MCQ flow: shuffled questions + shuffled options, per-question timer,
# then a results screen (optionally after a YouTube video/BGM).
# ---------------------------------------------------------------------------
@student_bp.route("/challenge/<int:challenge_id>/mcq")
@login_required
@role_required("student")
def mcq_start(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    if challenge.type != "mcq":
        return redirect(url_for("student.challenge_detail", challenge_id=challenge_id))

    allowed_category_ids = {c.id for c in challenge.categories}
    if current_user.category_id not in allowed_category_ids:
        return "Not authorized for this challenge.", 403

    questions = MCQQuestion.query.filter_by(challenge_id=challenge.id).all()
    answered_ids = {
        a.question_id for a in MCQAnswer.query.filter_by(user_id=current_user.id)
        if a.question_id in [q.id for q in questions]
    }
    remaining = [q for q in questions if q.id not in answered_ids]

    if not remaining:
        return redirect(url_for("student.mcq_result", challenge_id=challenge.id))

    random.shuffle(remaining)
    next_question = remaining[0]
    options = list(next_question.options)
    random.shuffle(options)

    return render_template(
        "student/mcq_question.html",
        challenge=challenge,
        question=next_question,
        options=options,
        remaining_count=len(remaining),
        total_count=len(questions),
        time_limit=challenge.time_limit_seconds or 30,
    )


@student_bp.route("/challenge/<int:challenge_id>/mcq/answer", methods=["POST"])
@login_required
@role_required("student")
def mcq_answer(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    question_id = request.form.get("question_id", type=int)
    option_id = request.form.get("option_id", type=int)  # may be None if timer ran out

    question = MCQQuestion.query.get_or_404(question_id)

    existing = MCQAnswer.query.filter_by(user_id=current_user.id, question_id=question_id).first()
    if existing:
        return redirect(url_for("student.mcq_start", challenge_id=challenge_id))

    is_correct = False
    points = 0
    if option_id:
        option = MCQOption.query.get(option_id)
        if option and option.is_correct:
            is_correct = True
            points = question.points

    db.session.add(MCQAnswer(
        user_id=current_user.id, question_id=question_id,
        selected_option_id=option_id, is_correct=is_correct, points_awarded=points,
    ))
    if is_correct:
        current_user.total_score = (current_user.total_score or 0) + points
    db.session.commit()

    return redirect(url_for("student.mcq_start", challenge_id=challenge_id))


@student_bp.route("/challenge/<int:challenge_id>/mcq/result")
@login_required
@role_required("student")
def mcq_result(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    questions = MCQQuestion.query.filter_by(challenge_id=challenge.id).all()
    answers = MCQAnswer.query.filter(
        MCQAnswer.user_id == current_user.id,
        MCQAnswer.question_id.in_([q.id for q in questions])
    ).all()
    score = sum(a.points_awarded for a in answers)
    correct_count = sum(1 for a in answers if a.is_correct)

    video_url = Setting.get("mcq_result_video_url", "")
    bgm_url = Setting.get("mcq_bgm_url", "")

    return render_template(
        "student/mcq_result.html",
        challenge=challenge,
        score=score,
        correct_count=correct_count,
        total=len(questions),
        video_url=video_url,
        bgm_url=bgm_url,
    )


@student_bp.route("/scoreboard")
@login_required
@role_required("student")
def scoreboard():
    category = Category.query.get(current_user.category_id) if current_user.category_id else None
    frozen = category.scoreboard_frozen if category else False

    students = []
    if category:
        students = (
            User.query.filter_by(role="student", category_id=category.id)
            .order_by(User.total_score.desc(), User.last_submission_at.asc())
            .all()
        )

    return render_template(
        "student/scoreboard.html", students=students, category=category, frozen=frozen
    )
