import os
from flask import Flask
from flask_login import LoginManager

from config import Config
from models import db, User, Setting, DEFAULT_SETTINGS

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to continue."
app = Flask(__name__)

def create_app():
    app.config.from_object(Config)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    login_manager.init_app(app)

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.staff import staff_bp
    from routes.student import student_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(student_bp, url_prefix="/event")
    app.register_blueprint(api_bp, url_prefix="/api")

    db.create_all()

    for key, value in DEFAULT_SETTINGS.items():
        if Setting.get(key) is None:
            Setting.set(key, value)

    if not User.query.filter_by(role="admin").first():
        admin = User(username="admin", name="Administrator", role="admin")
        admin.set_password("Admin@12345")
        db.session.add(admin)
        db.session.commit()
        print("=" * 60)
        print(" Default admin created -> username: admin  password: Admin@12345")
        print(" CHANGE THIS PASSWORD IMMEDIATELY AFTER FIRST LOGIN.")
        print("=" * 60)

    return app

@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except (TypeError, ValueError):
        return None

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
