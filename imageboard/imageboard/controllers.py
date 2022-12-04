import io
import json
import requests
from flask import render_template, send_file
from werkzeug.exceptions import ServiceUnavailable, BadRequest


class FileServerController(object):
    def __init__(self, app=None):
        self.app = app

    def get_image(self, link):
        return self.get_link(link, must_be_image=True)

    def get_link_json(self, link):
        pass

    def get_link_as_json(self, link, must_be_image=False):
        link = link.replace('$', '/')
        file_format = link.split('.')[-1].lower()

        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        if must_be_image and req.headers.get('Content-Type').split('/')[0].strip() != 'image':
            raise BadRequest("[BAD_FILE_2] Returned data was not an image")

        data = req.raw.read()
        return json.loads(data)

    def get_link(self, link, must_be_image=False):
        """Fetches images from image server. Link must replace / with $."""
        link = link.replace('$', '/')
        file_format = link.split('.')[-1].lower()

        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        if must_be_image and req.headers.get('Content-Type').split('/')[0].strip() != 'image':
            raise BadRequest("[BAD_FILE_3] Returned data was not an image")

        data = req.raw.read()
        return send_file(
            io.BytesIO(data),
            mimetype=req.headers.get('Content-Type', 'image/jpeg'),
            as_attachment=False,
            download_name=link.split('/')[-1]
        )

    def reference_image(self, image_name, link):
        print(f'referencing image {image_name}, link: {link}')