"""Application factory and shared Flask extensions."""

import hmac
import ipaddress
import logging
from datetime import datetime, timezone
from uuid import uuid4

import click
from flask import Flask, abort, current_app, g, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text

from .database import User, db
from .settings import configure_app, validate_config

csrf = CSRFProtect()
login_manager = LoginManager()


def rate_limit_identity():
    if current_user.is_authenticated:
        return f'user:{current_user.id}'

    remote_address = get_remote_address()
    configured_networks = current_app.config.get('TRUSTED_PROXY_NETWORKS', '')
    if configured_networks and request.headers.get('X-Forwarded-For'):
        try:
            remote_ip = ipaddress.ip_address(remote_address)
            networks = [
                ipaddress.ip_network(network.strip())
                for network in configured_networks.split(',')
                if network.strip()
            ]
            if any(remote_ip in network for network in networks):
                # Trust the address added by the trusted reverse proxy (the
                # right-most value), not the client-controllable left-most value.
                forwarded = request.headers['X-Forwarded-For'].rsplit(',', 1)[-1].strip()
                return f'ip:{ipaddress.ip_address(forwarded)}'
        except ValueError:
            pass
    return f'ip:{remote_address}'


limiter = Limiter(key_func=rate_limit_identity)
migrate = Migrate()


def create_app(test_config=None):
    app = Flask(__name__)
    configure_app(app)
    if test_config:
        app.config.update(test_config)
    validate_config(app)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    from .application import main_pages
    from .auth import auth_pages
    from .images import image_pages

    app.register_blueprint(auth_pages)
    app.register_blueprint(main_pages)
    app.register_blueprint(image_pages)

    register_commands(app)
    register_request_security(app)
    register_error_handlers(app)

    @app.context_processor
    def template_context():
        return {'year': datetime.now(timezone.utc).year}

    return app


@login_manager.user_loader
def load_user(user_id):
    if not user_id.isdigit():
        return None
    user = db.session.get(User, int(user_id))
    return None if user is None or user.banned else user


def register_commands(app):
    @app.cli.command('create-user')
    @click.option('--username', prompt=True)
    @click.option('--admin/--no-admin', default=False)
    @click.password_option(confirmation_prompt=True)
    def create_user(username, admin, password):
        """Create a local account; public registration is intentionally disabled."""
        username = User.normalize_name(username)
        if User.query.filter(db.func.lower(User.name) == username.lower()).first():
            raise click.ClickException('That username already exists.')
        if len(password) < 14:
            raise click.ClickException('Passwords must contain at least 14 characters.')

        user = User(name=username, privileges='admin' if admin else 'user', banned=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'Created {"administrator" if admin else "user"} {username}.')


def register_request_security(app):
    @app.before_request
    def require_private_access():
        g.request_id = uuid4().hex
        public_endpoints = {'auth.login', 'health_live', 'health_ready', 'static'}
        if request.endpoint not in public_endpoints and not current_user.is_authenticated:
            return login_manager.unauthorized()
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self'; media-src 'self'; style-src 'self'"
        )
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), geolocation=(), microphone=()'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Request-ID'] = g.get('request_id', uuid4().hex)
        if app.config['ENABLE_HSTS']:
            response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'
        if response.mimetype == 'text/html':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/health/live')
    @limiter.exempt
    def health_live():
        return jsonify(status='ok')

    @app.get('/health/ready')
    @limiter.limit('60 per minute')
    def health_ready():
        supplied_token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        expected_token = app.config.get('HEALTH_TOKEN') or ''
        if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
            abort(404)
        try:
            db.session.execute(text('SELECT 1'))
        except Exception:
            db.session.rollback()
            return jsonify(status='unavailable'), 503
        return jsonify(status='ok')


def register_error_handlers(app):
    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def expected_error(error):
        return render_template('error.html', title='Request error', error=error), error.code

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error('Unhandled request error request_id=%s', g.get('request_id'), exc_info=True)
        return render_template(
            'error.html', title='Server error', error='The request could not be completed.'
        ), 500

    if not app.debug:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)
