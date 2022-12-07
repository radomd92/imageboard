from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

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
    image = db.Column(db.Integer, db.ForeignKey('image.id'))


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
    def rating(self):
        return 0

    @property
    def comments(self):
        return []


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
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
