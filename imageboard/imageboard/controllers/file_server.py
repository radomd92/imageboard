"""Constrained client for the external Nginx media origin."""

import json
import time
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

import requests
from flask import current_app
from werkzeug.exceptions import BadGateway, BadRequest, RequestEntityTooLarge

from ..audit import record_event
from ..database import Image, db
from ..model.image import Image as ImageModel

IMAGE_MIME_TYPES = {
    'image/avif',
    'image/bmp',
    'image/gif',
    'image/jpeg',
    'image/png',
    'image/tiff',
    'image/webp',
}
VIDEO_MIME_TYPES = {
    'video/mp4',
    'video/quicktime',
    'video/webm',
    'video/x-msvideo',
    'video/x-ms-wmv',
}
MEDIA_MIME_TYPES = IMAGE_MIME_TYPES | VIDEO_MIME_TYPES
MEDIA_EXTENSIONS = {
    'avif', 'avi', 'bmp', 'gif', 'jpeg', 'jpg', 'm4v', 'mov', 'mp4', 'png', 'tif', 'tiff',
    'webm', 'webp', 'wmv',
}
VIDEO_EXTENSIONS = {'avi', 'm4v', 'mov', 'mp4', 'webm', 'wmv'}


def canonical_media_path(link, allow_empty=False):
    raw = (link or '').replace('$', '/')
    if not raw:
        if allow_empty:
            return ''
        raise BadRequest('A media path is required.')
    if raw.startswith('/') or '\\' in raw or '\x00' in raw:
        raise BadRequest('Invalid media path.')

    path = PurePosixPath(raw)
    parts = raw.split('/')
    if path.is_absolute() or any(
        not part
        or part in {'.', '..'}
        or '$' in part
        or len(part.encode('utf-8')) > 255
        or any(unicodedata.category(char).startswith('C') for char in part)
        for part in parts
    ):
        raise BadRequest('Invalid media path.')
    return '$'.join(parts)


def is_supported_media(path):
    return path.rsplit('.', 1)[-1].lower() in MEDIA_EXTENSIONS if '.' in path else False


class FileServerController:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def get_directory(self, link=''):
        canonical = canonical_media_path(link, allow_empty=True)
        response = self._request(canonical)
        try:
            content_type = self._content_type(response)
            if content_type not in {'application/json', 'text/json'}:
                raise BadGateway('The media origin returned an invalid directory response.')
            payload = self._read_limited(response, current_app.config['MAX_DIRECTORY_BYTES'])
            listing = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise BadGateway('The media origin returned malformed JSON.') from error
        finally:
            response.close()

        if not isinstance(listing, list) or len(listing) > 10_000:
            raise BadGateway('The media origin returned an invalid directory listing.')
        return [self._validate_listing_item(item) for item in listing]

    def open_media(self, link, thumbnail_size=None):
        canonical = canonical_media_path(link)
        if not is_supported_media(canonical):
            raise BadRequest('Unsupported media type.')
        extension = canonical.rsplit('.', 1)[-1].lower()

        request_path = canonical
        if thumbnail_size:
            if thumbnail_size not in {'small', 'large'}:
                raise BadRequest('Invalid thumbnail size.')
            request_path += '§vthumb' if extension in VIDEO_EXTENSIONS else f'§thumb§{thumbnail_size}'

        response = self._request(request_path)
        content_type = self._content_type(response)
        allowed_types = IMAGE_MIME_TYPES if thumbnail_size else MEDIA_MIME_TYPES
        if content_type not in allowed_types:
            response.close()
            raise BadGateway('The media origin returned an unsupported content type.')

        content_length = response.headers.get('Content-Length')
        if content_length:
            try:
                if int(content_length) > current_app.config['MAX_MEDIA_BYTES']:
                    response.close()
                    raise RequestEntityTooLarge()
            except ValueError as error:
                response.close()
                raise BadGateway('The media origin returned an invalid content length.') from error
        return response, content_type, canonical.rsplit('$', 1)[-1]

    def iter_media(self, response):
        total = 0
        maximum = current_app.config['MAX_MEDIA_BYTES']
        deadline = time.monotonic() + current_app.config['MAX_STREAM_SECONDS']
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > maximum:
                    current_app.logger.warning('Media origin exceeded configured response limit')
                    return
                if time.monotonic() > deadline:
                    current_app.logger.warning('Media origin exceeded configured stream deadline')
                    return
                yield chunk
        finally:
            response.close()

    def reference_image(self, image_name, link, size=None, uploader_id=None):
        canonical = canonical_media_path(link)
        if not is_supported_media(canonical):
            return None
        try:
            file_size = int(size)
        except (TypeError, ValueError) as error:
            raise BadRequest('Invalid media file size.') from error
        if file_size < 0 or file_size > current_app.config['MAX_MEDIA_BYTES']:
            raise BadRequest('Media file is outside the permitted size range.')

        existing = Image.query.filter_by(image_path=canonical).first()
        safe_name = ' '.join((image_name or '').strip().split())
        if (
            not safe_name
            or len(safe_name) > 200
            or any(unicodedata.category(char).startswith('C') for char in safe_name)
        ):
            raise BadRequest('Invalid media filename.')
        if existing:
            if existing.name == existing.image_path.rsplit('$', 1)[-1]:
                existing.name = safe_name
            existing.file_size = file_size
            record_event('reindex', 'image', existing.id)
            db.session.commit()
            return ImageModel.from_db(existing)

        image = Image(
            name=safe_name,
            image_path=canonical,
            file_size=file_size,
            uploader=uploader_id,
        )
        db.session.add(image)
        db.session.flush()
        record_event('index', 'image', image.id)
        db.session.commit()
        return ImageModel.from_db(image)

    def _request(self, canonical_path):
        base_url = current_app.config['FILE_SERVER'].rstrip('/')
        encoded_path = '/'.join(quote(part, safe='') for part in canonical_path.split('$') if part)
        url = f'{base_url}/{encoded_path}'
        username = current_app.config.get('FILE_SERVER_USERNAME')
        password = current_app.config.get('FILE_SERVER_PASSWORD')
        auth = (username, password) if username and password else None
        try:
            response = self.session.get(
                url,
                auth=auth,
                allow_redirects=False,
                stream=True,
                timeout=(
                    current_app.config['FILE_SERVER_TIMEOUT_CONNECT'],
                    current_app.config['FILE_SERVER_TIMEOUT_READ'],
                ),
                verify=current_app.config['FILE_SERVER_CA_BUNDLE'],
                headers={'Accept-Encoding': 'identity'},
            )
        except requests.RequestException as error:
            raise BadGateway('The media origin is unavailable.') from error
        if response.status_code != 200:
            response.close()
            raise BadGateway('The media origin rejected the request.')
        return response

    @staticmethod
    def _content_type(response):
        return response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()

    @staticmethod
    def _read_limited(response, maximum):
        content_length = response.headers.get('Content-Length')
        if content_length:
            try:
                if int(content_length) > maximum:
                    raise RequestEntityTooLarge()
            except ValueError as error:
                raise BadGateway('The media origin returned an invalid content length.') from error
        data = bytearray()
        for chunk in response.iter_content(chunk_size=16 * 1024):
            data.extend(chunk)
            if len(data) > maximum:
                raise RequestEntityTooLarge()
        return data.decode('utf-8')

    @staticmethod
    def _validate_listing_item(item):
        if not isinstance(item, dict) or set(item) - {'name', 'type', 'mtime', 'size'}:
            raise BadGateway('The media origin returned an invalid directory item.')
        name = item.get('name')
        item_type = item.get('type')
        if not isinstance(name, str) or item_type not in {'directory', 'file'}:
            raise BadGateway('The media origin returned an invalid directory item.')
        canonical_media_path(name)
        if '/' in name or '$' in name:
            raise BadGateway('The media origin returned a nested directory item.')
        if item_type == 'file' and not isinstance(item.get('size'), int):
            raise BadGateway('The media origin returned a file without a valid size.')
        return {'name': name, 'type': item_type, 'size': item.get('size')}
