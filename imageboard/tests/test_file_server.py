import pytest
from werkzeug.exceptions import BadGateway, BadRequest, RequestEntityTooLarge

from imageboard.controllers.file_server import FileServerController, canonical_media_path


class FakeResponse:
    def __init__(self, status=200, content_type='image/jpeg', data=b'jpeg', length=None):
        self.status_code = status
        self.headers = {'Content-Type': content_type}
        if length is not None:
            self.headers['Content-Length'] = str(length)
        self.data = data
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.data

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.parametrize('path', ['../secret.jpg', '..$secret.jpg', '/absolute.jpg', 'a\\b.jpg', 'a$$b.jpg'])
def test_canonical_path_rejects_traversal(path):
    with pytest.raises(BadRequest):
        canonical_media_path(path)


def test_origin_request_is_verified_bounded_and_does_not_redirect(app):
    response = FakeResponse()
    session = FakeSession(response)
    controller = FileServerController(session=session)
    with app.app_context():
        upstream, mimetype, _ = controller.open_media('album$example.jpg')
    assert upstream is response
    assert mimetype == 'image/jpeg'
    url, options = session.calls[0]
    assert url == 'https://media.example.test/images/album/example.jpg'
    assert options['allow_redirects'] is False
    assert options['verify'] is True
    assert options['timeout'] == (3, 20)
    assert options['headers']['Accept-Encoding'] == 'identity'


def test_origin_redirect_and_active_content_are_rejected(app):
    with app.app_context():
        with pytest.raises(BadGateway):
            FileServerController(FakeSession(FakeResponse(status=302))).open_media('album$example.jpg')
        with pytest.raises(BadGateway):
            FileServerController(FakeSession(FakeResponse(content_type='text/html'))).open_media('album$example.jpg')


def test_origin_size_limit_is_enforced(app):
    response = FakeResponse(length=app.config['MAX_MEDIA_BYTES'] + 1)
    with app.app_context(), pytest.raises(RequestEntityTooLarge):
        FileServerController(FakeSession(response)).open_media('album$example.jpg')


def test_chunked_origin_size_limit_is_enforced(app):
    response = FakeResponse(data=b'1234')
    controller = FileServerController(FakeSession(response))
    with app.app_context():
        app.config['MAX_MEDIA_BYTES'] = 3
        assert list(controller.iter_media(response)) == []
    assert response.closed


def test_directory_listing_is_strict(app):
    response = FakeResponse(
        content_type='application/json', data=b'[{"name":"photo.jpg","type":"file","size":1}]'
    )
    with app.app_context():
        listing = FileServerController(FakeSession(response)).get_directory('album')
    assert listing == [{'name': 'photo.jpg', 'type': 'file', 'size': 1}]

    nested = FakeResponse(content_type='application/json', data=b'[{"name":"../secret","type":"directory"}]')
    with app.app_context(), pytest.raises(BadRequest):
        FileServerController(FakeSession(nested)).get_directory('album')
