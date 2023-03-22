from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

# create the extension
db = SQLAlchemy()


class Rating(db.Model):
    __tablename__ = 'ratings'

    id = db.Column(db.Integer, primary_key=True)
    user = db.Column(db.Integer, db.ForeignKey('user.id'))
    image = db.Column(db.Integer, db.ForeignKey('image.id'))
    rating = db.Column(db.Integer)
    date = db.Column(db.DateTime(timezone=True), server_default=func.now())


class Tag(db.Model):
    __tablename__ = 'tag'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))


class TagImage(db.Model):
    __tablename__ = 'tag_image'
    __table_args__ = (
        db.UniqueConstraint('tag', 'image', name='unique_component_commit'),
    )
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.Integer, db.ForeignKey('image.id'))
    tag = db.Column(db.Integer, db.ForeignKey('tag.id'))


class Image(db.Model):
    __tablename__ = 'image'

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.Text,  unique=True)
    name = db.Column(db.String(200), nullable=False)
    created_date = db.Column(db.DateTime(timezone=True), server_default=func.now())
    file_size = db.Column(db.Integer)
    hits = db.Column(db.Integer)
    uploader = db.Column(db.Integer, db.ForeignKey('user.id'))

    @property
    def tags(self):
        ret = []
        tags_for_image = db.session.query(TagImage, Tag.name)\
            .join(Tag)\
            .filter(TagImage.image == self.id)
        for tag_image, data in tags_for_image:
            ret.append(Tag(name=data, id=tag_image))

        return ret

    @property
    def rating(self):
        return 0

    @property
    def comments(self):
        return []


class ImageHit(db.Model):
    __tablename__ = 'image_hits'

    hit_id = db.Column(UUID, primary_key=True, server_default=text("uuid_generate_v4()"))
    image_id = db.Column(db.Integer, primary_key=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    hit_date = db.Column(db.DateTime(timezone=True), server_default=func.now())
    type = db.Column(db.String(16))


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    password = db.Column(db.String(256))
    registered = db.Column(db.DateTime(timezone=True))
    karma = db.Column(db.Integer)
    privileges = db.Column(db.String(100))
    banned = db.Column(db.Boolean)


class Message(db.Model):
    __tablename__ = 'message'

    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id'))
    image = db.Column(db.Integer, db.ForeignKey('image.id'))
    text = db.Column(db.String(500))
    reply_to = db.Column(db.Integer, db.ForeignKey('message.id'))
    message_date = db.Column(db.DateTime(timezone=True))

    _replies = []
    _function_was_called = False

    @classmethod
    def get_by_id(self, id_: int) -> 'Message':
        data = db.session.query(Message).filter(Message.id == id_).one()
        data.fetch_replies()
        return data

    def fetch_replies(self):
        self._function_was_called = True
        db_replies = db.session.query(Message).filter(Message.reply_to == self.id).all()
        if not db_replies:
            self._replies = []
        else:
            for reply in db_replies:
                reply.fetch_replies()

            self._replies = db_replies

    @property
    def replies(self):
        if not self._function_was_called:
            self.fetch_replies()
        return self._replies
