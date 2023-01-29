from _sha256 import sha256
import json
import os
from pickle import dumps, loads
from random import randbytes
from redis import Redis
import rsa
from Crypto.Cipher import AES
import requests
from werkzeug.exceptions import ServiceUnavailable, BadRequest
from .. import db
from ..database import Image
from ..model.image import Image as ImageModel
from .exceptions import CacheError


def pad(data: bytes) -> bytes:
    while len(data) % 16 != 0:
        data += b'1'
    return data


class RedisCache(object):
    def __init__(self, app):
        self.app = app
        self.redis = Redis()

    def add_data(self, link, data, content_type):
        link_hash = sha256(link.encode('utf-8')).hexdigest()
        self.redis.set(link_hash, dumps(data))
        self.redis.set(link_hash + '_content_type', content_type)

    def get_data(self, link):
        link_hash = sha256(link.encode('utf-8')).hexdigest()
        cached_data = self.redis.get(link_hash)
        content_type = self.redis.get(link_hash + '_content_type')
        if cached_data:
            return loads(cached_data), str(content_type, 'utf8')
        else:
            return None, None


class EncryptedFilesystemCache(object):
    def __init__(self, app):
        self.app = app
        self.folder = 'imageboard_cache'
        self.keys_folder = 'config/keys'

        self.key_size_bits = 2048
        self.private_key = None
        self.public_key = None

        if not os.path.exists(self.folder):
            os.mkdir(self.folder)

        self.load_keypair()

    @property
    def aes_key(self):
        return randbytes(32)

    def load_keypair(self):
        if os.path.exists(f'{self.keys_folder}/rsa.key'):
            with open(f'{self.keys_folder}/rsa.key', 'rb') as private_key:
                self.private_key = rsa.PrivateKey.load_pkcs1(private_key.read())
            with open(f'{self.keys_folder}/rsa_pub.key', 'rb') as public_key:
                self.public_key = rsa.PublicKey.load_pkcs1(public_key.read())
        else:
            try:
                print(f"Generating {self.key_size_bits}-bit key pair for local cache storage...")
                self._generate_rsa_keypair_if_not_exists()
            except Exception as unknown_error:
                raise CacheError(f"Failed to load keypair: {unknown_error}") from unknown_error

    def _generate_rsa_keypair_if_not_exists(self):
        if not os.path.exists(self.keys_folder):
            os.makedirs(self.keys_folder)

        if not os.path.exists(f'{self.keys_folder}/rsa.key'):
            self.public_key, self.private_key = rsa.newkeys(self.key_size_bits)
            public_key_as_bytes, private_key_as_bytes = self.public_key.save_pkcs1(), self.private_key.save_pkcs1()
            with open(f'{self.keys_folder}/rsa.key', 'wb') as private_key_file:
                private_key_file.write(private_key_as_bytes)
            with open(f'{self.keys_folder}/rsa_pub.key', 'wb') as public_key_file:
                public_key_file.write(public_key_as_bytes)

    def add_data(self, link, data, content_type, raise_on_ioerror=False):
        aes_key = self.aes_key
        aes = AES.new(aes_key)
        link_hash = sha256(link.encode('utf-8')).hexdigest()
        with open(f'{self.folder}/{link_hash}', 'wb') as file:
            try:
                data_pkg = (
                    aes.encrypt(pad(bytes(data))),
                    len(data),
                    # ^ [1] If data is not a multiple of 16. More characters have to be padded to make its length.
                    #   a multiple of 16. This information is then used to eliminate those padded characters
                    #   at decryption time.
                    aes.encrypt(pad(bytes(content_type, encoding='utf8'))),
                    len(content_type),  # Same as above
                    rsa.encrypt(aes_key, self.public_key)
                )
                pickled = dumps(data_pkg)
                file.write(pickled)
            except IOError as error:
                if raise_on_ioerror:
                    raise CacheError("Failed to write data on filesystem") from error

    def get_data(self, link):
        link_hash = sha256(link.encode('utf-8')).hexdigest()
        try:
            with open(f'{self.folder}/{link_hash}', 'rb') as file:
                aes_encrypted_data, \
                    data_length, \
                    content_type, \
                    content_type_length, \
                    rsa_encrypted_aes_key = loads(file.read())
                decrypted_key = rsa.decrypt(rsa_encrypted_aes_key, self.private_key)
                aes = AES.new(decrypted_key)
                return aes.decrypt(aes_encrypted_data)[:data_length], \
                    str(aes.decrypt(content_type)[:content_type_length])
                # ^ trimming data per reason [1] given above

        except FileNotFoundError:
            return None, None


class FileServerCache(object):
    def __init__(self, app):
        self.redis = RedisCache(app)
        self.filesystem = EncryptedFilesystemCache(app)

    def get_data(self, link):
        data, content_type = self.redis.get_data(link)
        if (data, content_type) != (None, None):
            return data, content_type

        data, content_type = self.filesystem.get_data(link)
        return data, content_type


class FileServerController(object):
    def __init__(self, app=None):
        self.app = app
        self.cache = FileServerCache(app)

    def get_image(self, link):
        return self.get_links(link)

    def get_links(self, link, must_be_image=False):
        data, content_type = self.cache.get_data(link)
        if (data, content_type) != (None, None):
            return data, content_type

        data, content = self._get_links(link, must_be_image)
        self.cache.redis.add_data(link, data, content)
        self.cache.filesystem.add_data(link, data, content)
        return data, content

    def _get_links(self, link, must_be_image=False):
        """Fetches images from image server. Link must replace / with $."""
        link = link.replace('$', '/')
        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        data = req.raw.read()
        content_type = req.headers.get('Content-Type').split('/')[0].strip()
        if must_be_image and content_type != 'image':
            raise BadRequest(f"[BAD_FILE_1] Returned data was not an image: Content-Type is '{content_type}'"
                             f" but 'image/*' was expected.")

        content_type = req.headers.get("Content-Type", 'image/jpeg')
        return data, content_type

    def get_link_as_json(self, link, must_be_image=False):
        link = link.replace('$', '/')

        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        content_type = req.headers.get('Content-Type').split('/')[0].strip()
        if must_be_image and content_type:
            raise BadRequest(f"[BAD_FILE_2] Returned data was not an image: Content-Type is '{content_type}'"
                             f" but 'image/*' was expected.")

        data = req.raw.read()
        return json.loads(data)

    def reference_image(self, image_name, link, size=None):
        with self.app.app_context():
            data = db.session.query(Image).filter_by(image_path=link).first()
            if data is None:
                if size is not None:
                    image = Image(name=image_name, image_path=link, file_size=size)
                    db.session.add(image)
                    db.session.commit()
                print(f'referencing image {image_name}, link: {link}')
            else:
                print(f'image {image_name} already referenced link: {link}: Image ID #{data.id}')
                return ImageModel.from_db(data)

    def reference_image_depth(self, image_name, link, depth, size=None):
        if depth == 0:
            return

        with self.app.app_context():
            if db.session.query(Image.id).filter_by(image_path=link).first() is None:
                if size is not None:
                    image = Image(name=image_name, image_path=link, file_size=size)
                    db.session.add(image)
                    db.session.commit()
                print('    ' * depth + f'referencing image {image_name}, link: {link}')
            else:
                print('    ' * depth + f'image {image_name} already referenced link: {link}')
