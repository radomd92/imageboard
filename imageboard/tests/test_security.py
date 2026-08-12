from imageboard import rate_limit_identity
from imageboard.database import AuditEvent, Image, Message, db
from tests.conftest import MEMBER_PASSWORD, csrf_token


def test_rate_limit_identity_ignores_spoofed_x_forwarded_for(app):
    with app.test_request_context(
        '/',
        environ_base={'REMOTE_ADDR': '10.0.0.1'},
        headers={'X-Forwarded-For': '1.1.1.1, 2.2.2.2'},
    ):
        # Without a trusted proxy the raw remote address is used and the
        # spoofed X-Forwarded-For values are ignored.
        app.config['TRUSTED_PROXY_NETWORKS'] = ''
        assert rate_limit_identity() == 'ip:10.0.0.1'

    with app.test_request_context(
        '/',
        environ_base={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-Forwarded-For': '1.1.1.1, 2.2.2.2'},
    ):
        # Behind a trusted proxy the right-most (proxy-added) address is used,
        # not the client-controllable left-most address.
        app.config['TRUSTED_PROXY_NETWORKS'] = '127.0.0.1/32'
        assert rate_limit_identity() == 'ip:2.2.2.2'

    with app.test_request_context(
        '/',
        environ_base={'REMOTE_ADDR': '127.0.0.1'},
        headers={'X-Forwarded-For': '1.1.1.1'},
    ):
        # A single X-Forwarded-For value is client-controlled, so it must be
        # ignored even when the request comes through a trusted proxy.
        app.config['TRUSTED_PROXY_NETWORKS'] = '127.0.0.1/32'
        assert rate_limit_identity() == 'ip:127.0.0.1'


def test_private_by_default_and_security_headers(client):
    response = client.get('/')
    assert response.status_code == 302
    assert '/auth/login' in response.headers['Location']

    health = client.get('/health/live')
    assert health.status_code == 200
    assert health.headers['Content-Security-Policy'].startswith("default-src 'self'")
    assert health.headers['X-Content-Type-Options'] == 'nosniff'
    assert health.headers['X-Frame-Options'] == 'DENY'
    assert health.headers['X-Request-ID']

    assert client.get('/health/ready').status_code == 404
    ready = client.get(
        '/health/ready', headers={'Authorization': 'Bearer test-health-token-that-is-long-enough'}
    )
    assert ready.status_code == 200


def test_csrf_is_required(client):
    response = client.post('/auth/login', data={'username': 'administrator', 'password': 'wrong'})
    assert response.status_code == 400


def test_login_rejects_external_redirect(client, login):
    response = login(next_url='https://attacker.example/steal')
    assert response.status_code == 302
    assert response.headers['Location'] == '/'


def test_non_admin_cannot_edit_or_explore(client, login):
    assert login('member', MEMBER_PASSWORD).status_code == 302
    assert client.get('/explore').status_code == 403
    assert client.get('/images/1/edit').status_code == 403


def test_admin_edit_requires_csrf_and_is_audited(app, client, login):
    login()
    assert client.post('/images/1/edit/title', data={'title': 'Changed'}).status_code == 400
    edit_page = client.get('/images/1/edit')
    response = client.post('/images/1/edit/title', data={
        'csrf_token': csrf_token(edit_page),
        'title': 'A safe title',
    })
    assert response.status_code == 303
    with app.app_context():
        assert db.session.get(Image, 1).name == 'A safe title'
        assert AuditEvent.query.filter_by(action='edit_title', object_id='1').count() == 1


def test_comment_validation_and_thread_loading(app, client, login):
    login('member', MEMBER_PASSWORD)
    detail = client.get('/images/1')
    token = csrf_token(detail)
    response = client.post('/images/1/comment', data={'csrf_token': token, 'comment': 'Hello'})
    assert response.status_code == 303
    with app.app_context():
        assert Message.query.one().text == 'Hello'
    page = client.get('/images/1')
    assert b'Hello' in page.data
    assert b'member' in page.data


def test_comment_depth_is_bounded(app, client, login):
    login('member', MEMBER_PASSWORD)
    with app.app_context():
        parent_id = None
        for index in range(8):
            message = Message(image=1, from_user=2, text=f'Level {index}', reply_to=parent_id)
            db.session.add(message)
            db.session.flush()
            parent_id = message.id
        db.session.commit()

    detail = client.get('/images/1')
    response = client.post('/images/1/comment', data={
        'csrf_token': csrf_token(detail),
        'comment': 'Too deep',
        'reply_to': parent_id,
    })
    assert response.status_code == 400
    assert b'cannot be nested' in response.data


def test_tag_payload_is_not_sql(client, login):
    login()
    response = client.get("/tags/x'%20OR%201=1--")
    assert response.status_code == 200
    assert b'No media uses this tag.' in response.data


def test_traversal_and_unindexed_media_are_rejected(client, login):
    login()
    assert client.get('/media/..$secret.jpg').status_code == 400
    assert client.get('/media/not-indexed.jpg').status_code == 404
