import json
import requests
from .database import Image
from .model.image import Image as ImageModel
from .serializers.image import Image as ImageSerializer
from . import db
from werkzeug.exceptions import ServiceUnavailable, BadRequest, NotFound


class FileServerController(object):
    def __init__(self, app=None):
        self.app = app

    def get_image(self, link):
        return self.get_links(link, must_be_image=True)

    def get_image_from_id(self, image_id):
        with self.app.app_context():
            db_image = db.session.query(Image).filter(Image.id == image_id).first()
            if db_image:
                return ImageModel.from_db(db_image)
            else:
                raise NotFound(f'No image with ID {image_id}')

    def get_link_as_json(self, link, must_be_image=False):
        link = link.replace('$', '/')

        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        if must_be_image and req.headers.get('Content-Type').split('/')[0].strip() != 'image':
            raise BadRequest("[BAD_FILE_2] Returned data was not an image")

        data = req.raw.read()
        return json.loads(data)

    def get_links(self, link, must_be_image=False):
        """Fetches images from image server. Link must replace / with $."""
        link = link.replace('$', '/')

        req = requests.get(f"{self.app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
        if req.status_code != 200:
            raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")

        if must_be_image and req.headers.get('Content-Type').split('/')[0].strip() != 'image':
            raise BadRequest("[BAD_FILE_3] Returned data was not an image")

        return req.raw.read(), req.headers.get("Content-Type", 'image/jpeg')

    def get_image_needing_tags(self):
        images = []

        with self.app.app_context():
            sql = "select " \
                  "id, image_path, name, created_date, file_size, hits, uploader, rating, tags " \
                  "from tagged_images " \
                  "limit 10;"
            query = db.session.execute(sql)
            for id, image_path, name, created_date, file_size, hits, uploader, rating, tags in query:
                img_model = ImageModel(
                    name=name, image_path=image_path, uploader=uploader,
                    file_size=file_size, hits=hits, rating=rating, tags=tags
                )
                serializer = ImageSerializer(img_model)
                images.append(serializer.serialize())

        return images

    def reference_image(self, image_name, link, size=None):
        with self.app.app_context():
            if db.session.query(Image.id).filter_by(image_path=link).first() is None:
                if size is not None:
                    image = Image(name=image_name, image_path=link, file_size=size)
                    db.session.add(image)
                    db.session.commit()
                print(f'referencing image {image_name}, link: {link}')
            else:
                print(f'image {image_name} already referenced link: {link}')
