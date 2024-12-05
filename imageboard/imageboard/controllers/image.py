from typing import Dict, List
from datetime import datetime
from .. import db
from ..database import Image, Tag, TagImage, Message, ImageHit
from ..model.image import Image as ImageModel, Tag as TagModel
from ..model.social import Message as MessageModel
from ..serializers import serialize_date
from ..serializers.image import Image as ImageSerializer
from ..controllers import BaseController
from sqlalchemy.sql import text

from .exceptions import NoSuchImageException, PageSaveError


class TagController(BaseController):
    def get_tag_by_name(self, tag_name) -> TagModel:
        with self.app.app_context():
            db_tag = db.session.query(Tag.id).filter(Tag.name == tag_name).first()
            if not db_tag:
                new_tag = Tag(name=tag_name)
                db.session.add(new_tag)
                db.session.commit()

        with self.app.app_context():
            db_tag = db.session.query(Tag).filter(Tag.name == tag_name).first()
            return TagModel.from_db(db_tag)

    def get_monthly_viewed(self) -> List[Dict]:
        monthly_viewed = []
        with self.app.app_context():
            sql = " select tag, visits, last_visited, most_viewed_image_id, most_viewed_image_path" \
                      " from most_visited_tags " \
                      " where visits > 2" \
                      " order by visits desc" \
                      " limit 25;"
            query = db.session.execute(sql)
            monthly_viewed.extend(
                {
                    'tag': tag,
                    'visits': visits,
                    'last_visited': serialize_date(last_visited),
                    'most_viewed_image_id': most_viewed_image_id,
                    'most_viewed_image_path': most_viewed_image_path,
                }
                for tag, visits, last_visited, most_viewed_image_id, most_viewed_image_path in query
            )
        return monthly_viewed


class ImageController(BaseController):

    RESULTS_PER_PAGE = 30

    def add_comment(self, image_id, message_text, reply_to=None):
        with self.app.app_context():
            message = Message(image=image_id, text=message_text, reply_to=reply_to, message_date=datetime.now())
            db.session.add(message)
            db.session.commit()
            return self.get_image_from_id(image_id)

    def load_comments(self, image_id) -> List[MessageModel]:
        with self.app.app_context():
            messages_db = (
                db.session.query(Message)
                .filter(Message.image == image_id)
                .filter(Message.reply_to is None)
            )
            return [MessageModel.from_db(message) for message in messages_db]

    def get_image_from_id(self, image_id) -> ImageModel:
        with self.app.app_context():
            if (
                db_image := db.session.query(Image)
                .filter(Image.id == image_id)
                .first()
            ):
                return ImageModel.from_db(db_image)
            else:
                raise NoSuchImageException(image_id)

    def get_image_from_link(self, link) -> ImageModel:
        with self.app.app_context():
            if (
                db_image := db.session.query(Image)
                .filter(Image.image_path == link)
                .first()
            ):
                return ImageModel.from_db(db_image)
            else:
                raise NoSuchImageException(link)

    def get_image_needing_tags(self, limit=8) -> List[ImageModel]:
        images = []

        with self.app.app_context():
            sql = "select " \
                  " id, image_path, name, created_date, file_size, hits, uploader, rating " \
                  " from tagged_images " \
                  " where tags is NULL " \
                  " order by created_date desc " \
                  f"limit {limit};"

            query = db.session.execute(sql)
            for image_id, image_path, name, created_date, file_size, hits, uploader, rating in query:
                img_model = ImageModel(
                    image_id=image_id, name=name, image_path=image_path, uploader=uploader, file_size=file_size,
                    hits=hits, rating=rating, tags=[]
                )
                images.append(img_model)

        return images

    def get_images_with_tag(self, tag_name, page=1):
        images = []
        sql = f"select tag_name, id from images_with_tag where tag_name = '{tag_name}'" \
              f" limit {self.RESULTS_PER_PAGE} offset {self.RESULTS_PER_PAGE*(page-1)};"
        with self.app.app_context():
            query = db.session.execute(sql)
            for tag_name_, image_id in query:
                last_image = self.get_image_from_id(image_id)
                images.append({
                    'tag_name': tag_name_,
                    'image': ImageSerializer(last_image).serialize(),
                })

        return images

    def get_tagged_images(self) -> List[ImageModel]:
        images = []

        with self.app.app_context():
            sql = "select " \
                  " id, image_path, name, created_date, file_size, hits, uploader, rating, tags" \
                  " from tagged_images" \
                  " where tags is not NULL" \
                  " order by created_date desc" \
                  " limit 8;"

            query = db.session.execute(sql)
            for image_id, image_path, name, created_date, file_size, hits, uploader, rating, tags in query:
                img_model = ImageModel(
                    image_id=image_id, name=name, image_path=image_path, uploader=uploader, file_size=file_size,
                    hits=hits, rating=rating, tags=tags
                )
                images.append(img_model)

        return images

    def get_used_tags(self, min_images=3) -> List[Dict]:
        tags = []
        sql = f"select name, images, max from tag_with_last_imageid where max >= {min_images};"
        with self.app.app_context():
            query = db.session.execute(sql)
            for tag_name_, images, last_image_id in query:
                last_image = self.get_image_from_id(last_image_id)
                if images >= min_images:
                    tags.append({
                        'tag_name': tag_name_,
                        'last_image': ImageSerializer(last_image).serialize(),
                        'images': images
                    })

            return tags

    def register_hit(self, image_id, view_type='image'):
        with self.app.app_context():
            hit = ImageHit(image_id=image_id, user_id=None, type=view_type)
            db.session.add(hit)
            image_table_data = db.session.query(Image).filter_by(id=image_id).first()
            if image_table_data is not None:
                if image_table_data.hits is None:
                    image_table_data.hits = 1
                else:
                    image_table_data.hits += 1

                db.session.commit()
            else:
                db.session.rollback()
                raise NoSuchImageException(image_id)

    def set_image_title(self, image_id, title):
        if not title:
            return
        with self.app.app_context():
            if not (
                db_image := db.session.query(Image)
                .filter(Image.id == image_id)
                .first()
            ):
                raise NoSuchImageException(f'[ERR_SET_IMAGE_TITLE_NO_IMAGE] No image with ID {image_id}')
            try:
                db_image.name = title
                db.session.commit()
            except Exception as unknown_error:
                db.session.rollback()
                err_msg = f'[ERR_SET_IMAGE_TITLE_DB_SAVE_ERROR] Could not set an image title: {unknown_error}'
                raise PageSaveError(err_msg) from unknown_error

    def set_image_tags(self, image_id, tags: list):
        tag_controller = TagController(self.app)
        tags_as_models = []
        with self.app.app_context():
            tags_as_models.extend(tag_controller.get_tag_by_name(tag) for tag in tags)
            # Remove all tags
            db.session.query(TagImage).filter(TagImage.image == image_id).delete()

            # Add all tags
            for tag in tags_as_models:
                db_tag_image = db.session.query(TagImage) \
                        .filter(TagImage.image == image_id) \
                        .filter(TagImage.tag == tag.tag_id).first()
                if not db_tag_image:
                    new_tag_association = TagImage(tag=tag.tag_id, image=image_id)
                    db.session.add(new_tag_association)

            db.session.commit()

    def get_search_results(self, term, page=1) -> List[ImageModel]:
        images = []
        term = term.lower()

        with self.app.app_context():
            sql = text(
                (
                    "select "
                    + " id, image_path, name, created_date, file_size, hits, uploader, rating "
                    + " from tagged_images "
                    + " where lower(name) like :term or lower(image_path) like :term "
                    + " order by created_date desc "
                    + "limit :results_per_page offset :offset;"
                )
            )
            query = db.session.execute(
                sql,
                {
                    'term': f'%{term}%',
                    'results_per_page': self.RESULTS_PER_PAGE,
                    'offset': max(0, self.RESULTS_PER_PAGE * (page - 1)),
                },
            )
            print(query.cursor.query)
            for image_id, image_path, name, created_date, file_size, hits, uploader, rating in query:
                img_model = ImageModel(
                    image_id=image_id, name=name, image_path=image_path, uploader=uploader, file_size=file_size,
                    hits=hits, rating=rating, tags=[]
                )
                images.append(img_model)

        return images
