import re

import pytest

from imageboard import create_app
from imageboard.database import Image, User, db

ADMIN_PASSWORD = 'correct horse battery staple'
MEMBER_PASSWORD = 'member password is long enough'


@pytest.fixture
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-that-is-long-enough',
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'FILE_SERVER': 'https://media.example.test/images',
        'SESSION_COOKIE_SECURE': False,
        'REMEMBER_COOKIE_SECURE': False,
        'ENABLE_HSTS': False,
        'HEALTH_TOKEN': 'test-health-token-that-is-long-enough',
        'WTF_CSRF_ENABLED': True,
        'RATELIMIT_ENABLED': False,
        'TRUSTED_HOSTS': ['localhost'],
    })
    with application.app_context():
        db.create_all()
        admin = User(name='administrator', privileges='admin', banned=False)
        admin.set_password(ADMIN_PASSWORD)
        member = User(name='member', privileges='user', banned=False)
        member.set_password(MEMBER_PASSWORD)
        db.session.add_all([admin, member])
        db.session.flush()
        db.session.add(Image(
            name='Example image',
            image_path='album$example.jpg',
            file_size=1024,
            uploader=admin.id,
        ))
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(response):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


@pytest.fixture
def login(client):
    def perform(username='administrator', password=None, next_url='/'):
        password = password or ADMIN_PASSWORD
        page = client.get(f'/auth/login?next={next_url}')
        return client.post('/auth/login', data={
            'csrf_token': csrf_token(page),
            'username': username,
            'password': password,
            'next': next_url,
        })
    return perform
