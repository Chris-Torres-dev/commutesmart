from __future__ import annotations

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Log in to keep your commute plans synced."


@login_manager.user_loader
def load_user(user_id: str):
    if not user_id or user_id.startswith("guest-"):
        return None
    from models.user import User

    return User.query.get(int(user_id))


from models.profile import Profile  # noqa: E402,F401
from models.saved_plan import SavedPlan  # noqa: E402,F401
from models.spend_log import SpendLog  # noqa: E402,F401
from models.user import User  # noqa: E402,F401
