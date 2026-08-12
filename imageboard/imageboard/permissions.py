"""Authorization helpers."""

from functools import wraps

from flask import abort
from flask_login import current_user


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return function(*args, **kwargs)

    return wrapped
