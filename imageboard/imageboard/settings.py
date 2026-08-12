"""Environment-backed application configuration."""

import os
from urllib.parse import urlsplit


def _boolean(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {'1', 'true', 'yes', 'on'}


def _integer(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError as error:
        raise RuntimeError(f'{name} must be an integer') from error


def _ca_bundle():
    value = os.environ.get('IMAGEBOARD_FILE_SERVER_CA_BUNDLE')
    if value is None or value.lower() in {'1', 'true', 'yes', 'on'}:
        return True
    if value.lower() in {'0', 'false', 'no', 'off'}:
        raise RuntimeError('Disabling media-origin TLS verification is not supported')
    return value


def configure_app(app):
    trusted_hosts = [
        host.strip()
        for host in os.environ.get('IMAGEBOARD_TRUSTED_HOSTS', '').split(',')
        if host.strip()
    ]
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('IMAGEBOARD_SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('IMAGEBOARD_DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle': 300},
        FILE_SERVER=os.environ.get('IMAGEBOARD_FILE_SERVER'),
        FILE_SERVER_USERNAME=os.environ.get('IMAGEBOARD_FILE_SERVER_USERNAME'),
        FILE_SERVER_PASSWORD=os.environ.get('IMAGEBOARD_FILE_SERVER_PASSWORD'),
        FILE_SERVER_CA_BUNDLE=_ca_bundle(),
        FILE_SERVER_TIMEOUT_CONNECT=_integer('IMAGEBOARD_FILE_SERVER_CONNECT_TIMEOUT', 3),
        FILE_SERVER_TIMEOUT_READ=_integer('IMAGEBOARD_FILE_SERVER_READ_TIMEOUT', 20),
        MAX_STREAM_SECONDS=_integer('IMAGEBOARD_MAX_STREAM_SECONDS', 120),
        MAX_MEDIA_BYTES=_integer('IMAGEBOARD_MAX_MEDIA_BYTES', 250 * 1024 * 1024),
        MAX_DIRECTORY_BYTES=_integer('IMAGEBOARD_MAX_DIRECTORY_BYTES', 2 * 1024 * 1024),
        MAX_CONTENT_LENGTH=_integer('IMAGEBOARD_MAX_FORM_BYTES', 64 * 1024),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_boolean('IMAGEBOARD_SECURE_COOKIES', True),
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=_boolean('IMAGEBOARD_SECURE_COOKIES', True),
        PERMANENT_SESSION_LIFETIME=3600,
        WTF_CSRF_TIME_LIMIT=3600,
        WTF_CSRF_SSL_STRICT=True,
        ENABLE_HSTS=_boolean('IMAGEBOARD_ENABLE_HSTS', True),
        TRUSTED_HOSTS=trusted_hosts or None,
        TRUSTED_PROXY_NETWORKS=os.environ.get('IMAGEBOARD_TRUSTED_PROXY_NETWORKS', ''),
        HEALTH_TOKEN=os.environ.get('IMAGEBOARD_HEALTH_TOKEN'),
        RATELIMIT_STORAGE_URI=os.environ.get('IMAGEBOARD_RATE_LIMIT_STORAGE', 'memory://'),
        RATELIMIT_DEFAULT='300 per hour',
        RATELIMIT_HEADERS_ENABLED=True,
    )


def validate_config(app):
    if app.testing:
        return

    required = {
        'IMAGEBOARD_SECRET_KEY': app.config.get('SECRET_KEY'),
        'IMAGEBOARD_DATABASE_URL': app.config.get('SQLALCHEMY_DATABASE_URI'),
        'IMAGEBOARD_FILE_SERVER': app.config.get('FILE_SERVER'),
        'IMAGEBOARD_TRUSTED_HOSTS': app.config.get('TRUSTED_HOSTS'),
        'IMAGEBOARD_HEALTH_TOKEN': app.config.get('HEALTH_TOKEN'),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f'Missing required configuration: {", ".join(missing)}')
    if len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('IMAGEBOARD_SECRET_KEY must contain at least 32 characters')
    if len(app.config['HEALTH_TOKEN']) < 32:
        raise RuntimeError('IMAGEBOARD_HEALTH_TOKEN must contain at least 32 characters')

    file_server = urlsplit(app.config['FILE_SERVER'])
    if file_server.scheme != 'https' or not file_server.hostname:
        raise RuntimeError('IMAGEBOARD_FILE_SERVER must be an absolute HTTPS URL')
    if file_server.username or file_server.password:
        raise RuntimeError(
            'Supply file-server credentials through dedicated environment variables, not its URL'
        )
