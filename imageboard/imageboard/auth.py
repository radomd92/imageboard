"""Local authentication routes."""

from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from . import limiter
from .database import User, db

auth_pages = Blueprint('auth', __name__, url_prefix='/auth')
DUMMY_PASSWORD_HASH = generate_password_hash('not-a-real-password', method='scrypt')


def _safe_next_url(target):
    parsed = urlsplit(target or '')
    if (
        parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith('/')
        or '\\' in parsed.path
        or any(ord(character) < 32 for character in parsed.path)
    ):
        return url_for('main.home')
    return parsed.path + (f'?{parsed.query}' if parsed.query else '')


@auth_pages.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        username = ' '.join(request.form.get('username', '').strip().split())
        password = request.form.get('password', '')
        user = None
        if len(username) <= 100:
            user = User.query.filter(db.func.lower(User.name) == username.lower()).first()
        password_valid = check_password_hash(user.password if user else DUMMY_PASSWORD_HASH, password)
        if user is not None and password_valid and not user.banned:
            session.clear()
            login_user(user, remember=False, fresh=True)
            return redirect(_safe_next_url(request.form.get('next')))
        flash('Invalid username or password.', 'error')

    return render_template('login.html', title='Sign in', next_url=_safe_next_url(request.args.get('next')))


@auth_pages.post('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))
