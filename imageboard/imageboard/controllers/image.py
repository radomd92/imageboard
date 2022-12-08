from ..database import Image, Tag, TagImage
from ..model.image import Image as ImageModel, Tag as TagModel
from ..serializers.image import Image as ImageSerializer
from .. import db
from .. controllers import BaseController
from werkzeug.exceptions import NotFound


class TagController(BaseController):
    def get_tag_by_name(self, tagname):
        with self.app.app_context():
            db_tag = db.session.query(Tag.id).filter(Tag.name == tagname).first()
            if not db_tag:
                new_tag = Tag(name=tagname)
                db.session.add(new_tag)
                db.session.commit()

        with self.app.app_context():
            db_tag = db.session.query(Tag).filter(Tag.name == tagname).first()
            return TagModel.from_db(db_tag)


class ImageController(BaseController):

    def get_image_from_id(self, image_id):
        with self.app.app_context():
            db_image = db.session.query(Image).filter(Image.id == image_id).first()
            if db_image:
                return ImageModel.from_db(db_image)
            else:
                raise NotFound(f'[NO_IMAGE_0] No image with ID {image_id}')

    def get_tagged_images(self):
        images = []

        with self.app.app_context():
            sql = "select " \
                  "id, image_path, name, created_date, file_size, hits, uploader, rating, tags " \
                  "from tagged_images " \
                  "where tags is not NULL " \
                  "order by created_date desc " \
                  "limit 8;"

            query = db.session.execute(sql)
            for image_id, image_path, name, created_date, file_size, hits, uploader, rating, tags in query:
                img_model = ImageModel(
                    image_id=image_id, name=name, image_path=image_path, uploader=uploader, file_size=file_size,
                    hits=hits, rating=rating, tags=tags
                )
                serializer = ImageSerializer(img_model)
                images.append(serializer.serialize())

        return images

    def get_image_needing_tags(self):
        images = []

        with self.app.app_context():
            sql = "select " \
                  "id, image_path, name, created_date, file_size, hits, uploader, rating " \
                  "from tagged_images " \
                  "where tags is NULL " \
                  "order by created_date desc " \
                  "limit 8;"

            query = db.session.execute(sql)
            for image_id, image_path, name, created_date, file_size, hits, uploader, rating in query:
                img_model = ImageModel(
                    image_id=image_id, name=name, image_path=image_path, uploader=uploader, file_size=file_size,
                    hits=hits, rating=rating, tags=[]
                )
                serializer = ImageSerializer(img_model)
                images.append(serializer.serialize())

        return images

    def set_image_title(self, image_id, title):
        with self.app.app_context():
            db_image = db.session.query(Image).filter(Image.id == image_id).first()
            if db_image:
                return ImageModel.from_db(db_image)
            else:
                raise NotFound(f'[NO_IMAGE_1] No image with ID {image_id}')

    def set_image_tags(self, image_id, tags: list):
        tag_controller = TagController(self.app)
        tags_as_models = []
        with self.app.app_context():
            for tag in tags:
                tags_as_models.append(tag_controller.get_tag_by_name(tag))

            # Remove all tags
            db.session.query(TagImage).filter(TagImage.image == image_id).delete()

            # Add all tags
            for tag in tags_as_models:
                db_tag_image = db.session.query(TagImage)\
                    .filter(TagImage.image == image_id)\
                    .filter(TagImage.tag == tag.tag_id).first()
                if not db_tag_image:
                    new_tag_association = TagImage(tag=tag.tag_id, image=image_id)
                    # print(tag.name, tag.tag_id, image_id)
                    db.session.add(new_tag_association)

            db.session.commit()


