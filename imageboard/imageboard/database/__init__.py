"""Relational data model."""

from datetime import datetime, timezone
from uuid import uuid4

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship
from werkzeug.security import check_password_hash, generate_password_hash


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Rating(db.Model):
    __tablename__ = 'ratings'
    __table_args__ = (CheckConstraint('rating >= 1 AND rating <= 5', name='rating_between_1_and_5'),)

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    image = db.Column(db.Integer, db.ForeignKey('image.id', ondelete='CASCADE'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)


class Tag(db.Model):
    __tablename__ = 'tag'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    image_links = relationship('TagImage', back_populates='tag_record', cascade='all, delete-orphan')


class TagImage(db.Model):
    __tablename__ = 'tag_image'
    __table_args__ = (UniqueConstraint('tag', 'image', name='unique_tag_image'),)

    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.Integer, db.ForeignKey('image.id', ondelete='CASCADE'), nullable=False, index=True)
    tag = db.Column(db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), nullable=False, index=True)
    image_record = relationship('Image', back_populates='tag_links')
    tag_record = relationship('Tag', back_populates='image_links')


class Image(db.Model):
    __tablename__ = 'image'

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.Text, unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)
    file_size = db.Column(db.BigInteger)
    hits = db.Column(db.Integer, nullable=False, server_default='0')
    uploader = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    uploader_user = relationship('User', foreign_keys=[uploader])
    tag_links = relationship('TagImage', back_populates='image_record', cascade='all, delete-orphan')

    @property
    def tags(self):
        return [link.tag_record for link in self.tag_links]

    @property
    def rating(self):
        ratings = [entry.rating for entry in self.rating_entries]
        return sum(ratings) / len(ratings) if ratings else 0

    rating_entries = relationship('Rating', foreign_keys=[Rating.image], cascade='all, delete-orphan')


class ImageHit(db.Model):
    __tablename__ = 'image_hits'
    __table_args__ = (
        Index('image_hits_image_date_idx', 'image_id', 'hit_date'),
        CheckConstraint("type IN ('image', 'thumbnail')", name='valid_hit_type'),
    )

    hit_id = db.Column(db.Uuid(as_uuid=True), primary_key=True, default=uuid4)
    image_id = db.Column(db.Integer, db.ForeignKey('image.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    hit_date = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    type = db.Column(db.String(16), nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(512), nullable=False)
    registered = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    karma = db.Column(db.Integer, nullable=False, server_default='0')
    privileges = db.Column(db.String(100), nullable=False, server_default='user')
    banned = db.Column(db.Boolean, nullable=False, server_default=db.false())

    @staticmethod
    def normalize_name(name):
        normalized = ' '.join((name or '').strip().split())
        if not 3 <= len(normalized) <= 100 or any(char in normalized for char in '/\\\x00'):
            raise ValueError('Username must contain 3 to 100 valid characters.')
        return normalized

    def set_password(self, password):
        self.password = generate_password_hash(password, method='scrypt')

    def check_password(self, password):
        return bool(self.password) and check_password_hash(self.password, password)

    @property
    def is_active(self):
        return not self.banned

    @property
    def is_admin(self):
        return self.privileges == 'admin'


class Message(db.Model):
    __tablename__ = 'message'
    __table_args__ = (Index('message_image_date_idx', 'image', 'message_date'),)

    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    image = db.Column(db.Integer, db.ForeignKey('image.id', ondelete='CASCADE'), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    reply_to = db.Column(db.Integer, db.ForeignKey('message.id', ondelete='CASCADE'))
    message_date = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    author = relationship('User', foreign_keys=[from_user])


class AuditEvent(db.Model):
    __tablename__ = 'audit_event'
    __table_args__ = (Index('audit_event_date_idx', 'created_at'),)

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    action = db.Column(db.String(64), nullable=False)
    object_type = db.Column(db.String(64), nullable=False)
    object_id = db.Column(db.String(200), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    actor = relationship('User', foreign_keys=[actor_id])
