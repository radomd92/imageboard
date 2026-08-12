"""Image, tag, comment, and analytics operations."""

import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask_login import current_user
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from ..audit import record_event
from ..database import Image, ImageHit, Message, Tag, TagImage, db
from ..model.image import Image as ImageModel
from ..model.image import Tag as TagModel
from ..model.social import Message as MessageModel
from ..serializers.image import Image as ImageSerializer
from .exceptions import NoSuchImageException, PageSaveError


def _contains_control_characters(value):
    return any(unicodedata.category(character).startswith('C') for character in value)


class TagController:
    def get_tag_by_name(self, tag_name):
        tag_name = self.validate_tag(tag_name)
        db_tag = Tag.query.filter(func.lower(Tag.name) == tag_name.lower()).first()
        if db_tag:
            return TagModel.from_db(db_tag)

        db_tag = Tag(name=tag_name)
        db.session.add(db_tag)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            db_tag = Tag.query.filter(func.lower(Tag.name) == tag_name.lower()).one()
        return TagModel.from_db(db_tag)

    @staticmethod
    def validate_tag(tag_name):
        normalized = ' '.join((tag_name or '').strip().lower().split())
        if not normalized or len(normalized) > 100:
            raise PageSaveError('Tags must contain between 1 and 100 characters.')
        if '/' in normalized or '\\' in normalized or _contains_control_characters(normalized):
            raise PageSaveError('A tag contains unsupported characters.')
        return normalized

    def get_monthly_viewed(self):
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (
            db.session.query(Tag.name, Image.id, Image.image_path, func.count(ImageHit.hit_id))
            .join(TagImage, TagImage.tag == Tag.id)
            .join(Image, Image.id == TagImage.image)
            .join(ImageHit, ImageHit.image_id == Image.id)
            .filter(ImageHit.hit_date >= since, ImageHit.type == 'image')
            .group_by(Tag.name, Image.id, Image.image_path)
            .all()
        )
        grouped = defaultdict(list)
        for tag_name, image_id, image_path, visits in rows:
            grouped[tag_name].append((visits, image_id, image_path))

        result = []
        for tag_name, images in grouped.items():
            total_visits = sum(item[0] for item in images)
            visits, image_id, image_path = max(images)
            if total_visits >= 3:
                result.append({
                    'tag': tag_name,
                    'visits': total_visits,
                    'most_viewed_image_id': image_id,
                    'most_viewed_image_path': image_path,
                })
        return sorted(result, key=lambda item: item['visits'], reverse=True)[:25]


class ImageController:
    RESULTS_PER_PAGE = 30
    MAX_COMMENT_DEPTH = 8

    def add_comment(self, image_id, message_text, reply_to=None):
        image_id = self._positive_integer(image_id, 'image ID')
        text_value = (message_text or '').strip()
        if not text_value or len(text_value) > 500 or _contains_control_characters(text_value):
            raise PageSaveError('Comments must contain between 1 and 500 valid characters.')
        self.get_image_from_id(image_id)

        parent_id = None
        if reply_to:
            parent_id = self._positive_integer(reply_to, 'reply ID')
            parent = Message.query.filter_by(id=parent_id, image=image_id).first()
            if parent is None:
                raise PageSaveError('The comment being replied to does not belong to this image.')
            depth = 1
            while parent.reply_to is not None:
                depth += 1
                if depth >= self.MAX_COMMENT_DEPTH:
                    raise PageSaveError(
                        f'Comments cannot be nested more than {self.MAX_COMMENT_DEPTH} levels.'
                    )
                parent = db.session.get(Message, parent.reply_to)
                if parent is None or parent.image != image_id:
                    raise PageSaveError('The comment thread is invalid.')

        message = Message(
            image=image_id,
            text=text_value,
            reply_to=parent_id,
            from_user=current_user.id,
        )
        db.session.add(message)
        record_event('comment', 'image', image_id)
        db.session.commit()
        return self.get_image_from_id(image_id)

    def load_comments(self, image_id):
        image_id = self._positive_integer(image_id, 'image ID')
        messages = (
            Message.query.options(selectinload(Message.author))
            .filter(Message.image == image_id)
            .order_by(Message.message_date.asc(), Message.id.asc())
            .all()
        )
        models = {message.id: MessageModel.from_db(message) for message in messages}
        roots = []
        for message in messages:
            model = models[message.id]
            if message.reply_to in models:
                models[message.reply_to].replies.append(model)
            else:
                roots.append(model)
        return roots

    def get_image_from_id(self, image_id):
        image_id = self._positive_integer(image_id, 'image ID')
        db_image = db.session.get(Image, image_id)
        if db_image is None:
            raise NoSuchImageException(image_id)
        return ImageModel.from_db(db_image)

    def get_image_from_link(self, link):
        db_image = Image.query.filter(Image.image_path == link).first()
        if db_image is None:
            raise NoSuchImageException(link)
        return ImageModel.from_db(db_image)

    def get_image_needing_tags(self, limit=8):
        limit = min(max(int(limit), 1), 50)
        images = (
            Image.query.options(selectinload(Image.tag_links).selectinload(TagImage.tag_record))
            .filter(~Image.tag_links.any())
            .order_by(Image.created_date.desc())
            .limit(limit)
            .all()
        )
        return [ImageModel.from_db(image) for image in images]

    def get_images_with_tag(self, tag_name, page=1):
        tag_name = TagController.validate_tag(tag_name)
        page = max(int(page), 1)
        images = (
            Image.query.join(TagImage).join(Tag)
            .filter(func.lower(Tag.name) == tag_name.lower())
            .order_by(Image.created_date.desc())
            .limit(self.RESULTS_PER_PAGE)
            .offset(self.RESULTS_PER_PAGE * (page - 1))
            .all()
        )
        return [
            {'tag_name': tag_name, 'image': ImageSerializer(ImageModel.from_db(image)).serialize()}
            for image in images
        ]

    def get_used_tags(self, min_images=3):
        min_images = max(int(min_images), 0)
        rows = (
            db.session.query(Tag.name, func.count(TagImage.image), func.max(TagImage.image))
            .join(TagImage, TagImage.tag == Tag.id)
            .group_by(Tag.id, Tag.name)
            .having(func.count(TagImage.image) >= min_images)
            .order_by(func.count(TagImage.image).desc(), Tag.name.asc())
            .all()
        )
        return [
            {
                'tag_name': tag_name,
                'last_image': ImageSerializer(self.get_image_from_id(last_image_id)).serialize(),
                'images': image_count,
            }
            for tag_name, image_count, last_image_id in rows
        ]

    def register_hit(self, image_id, view_type='image'):
        image_id = self._positive_integer(image_id, 'image ID')
        if view_type not in {'image', 'thumbnail'}:
            raise ValueError('Invalid view type')
        updated = db.session.execute(
            update(Image)
            .where(Image.id == image_id)
            .values(hits=func.coalesce(Image.hits, 0) + 1)
        )
        if updated.rowcount != 1:
            db.session.rollback()
            raise NoSuchImageException(image_id)
        db.session.add(ImageHit(image_id=image_id, user_id=current_user.id, type=view_type))
        db.session.commit()

    def set_image_title(self, image_id, title):
        image_id = self._positive_integer(image_id, 'image ID')
        normalized = ' '.join((title or '').strip().split())
        if not normalized or len(normalized) > 200 or _contains_control_characters(normalized):
            raise PageSaveError('Titles must contain between 1 and 200 valid characters.')
        db_image = db.session.get(Image, image_id)
        if db_image is None:
            raise NoSuchImageException(image_id)
        db_image.name = normalized
        record_event('edit_title', 'image', image_id)
        db.session.commit()
        return ImageModel.from_db(db_image)

    def set_image_tags(self, image_id, tags):
        image_id = self._positive_integer(image_id, 'image ID')
        db_image = db.session.get(Image, image_id)
        if db_image is None:
            raise NoSuchImageException(image_id)
        normalized_tags = list(dict.fromkeys(TagController.validate_tag(tag) for tag in tags if tag.strip()))
        if len(normalized_tags) > 50:
            raise PageSaveError('An image cannot have more than 50 tags.')

        try:
            db_image.tag_links.clear()
            for tag_name in normalized_tags:
                tag = Tag.query.filter(func.lower(Tag.name) == tag_name.lower()).first()
                if tag is None:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                db_image.tag_links.append(TagImage(tag_record=tag))
            record_event('edit_tags', 'image', image_id)
            db.session.commit()
        except IntegrityError as error:
            db.session.rollback()
            raise PageSaveError('Tags changed concurrently; please retry.') from error
        return ImageModel.from_db(db_image)

    def get_search_results(self, term, page=1):
        normalized = ' '.join((term or '').strip().split())
        if len(normalized) > 100 or _contains_control_characters(normalized):
            raise PageSaveError('Search terms cannot exceed 100 valid characters.')
        if not normalized:
            return []
        page = max(int(page), 1)
        pattern = f'%{normalized.lower()}%'
        images = (
            Image.query.filter(
                or_(func.lower(Image.name).like(pattern), func.lower(Image.image_path).like(pattern))
            )
            .order_by(Image.created_date.desc())
            .limit(self.RESULTS_PER_PAGE)
            .offset(self.RESULTS_PER_PAGE * (page - 1))
            .all()
        )
        return [ImageModel.from_db(image) for image in images]

    @staticmethod
    def _positive_integer(value, label):
        try:
            result = int(value)
        except (TypeError, ValueError) as error:
            raise NoSuchImageException(f'Invalid {label}') from error
        if result < 1:
            raise NoSuchImageException(f'Invalid {label}')
        return result
