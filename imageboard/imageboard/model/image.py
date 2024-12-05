from typing import List

from . import Model
from .social import User


class Tag(Model):
    def __init__(self, name, tag_id=None):
        self.tag_id = tag_id
        self.name = name

    @classmethod
    def from_db(cls, db_model):
        return Tag(db_model.name, tag_id=db_model.id)

    def __repr__(self):
        return f"Tag({self.name}, id={self.tag_id})"


class Image(Model):
    def __init__(self, name: str, image_path: str, uploader: User, image_id=None,
                 file_size=0, hits=0, rating=0, created_date=None, tags: list = None):
        self.name = name
        self.created_date = created_date
        self.image_path = image_path
        self.uploader = uploader
        self.image_id = image_id
        self.file_size = file_size
        self.hits = hits
        self.rating = rating
        self.tags = tags

    @classmethod
    def from_db(cls, db_model):
        return Image(
            name=db_model.name,
            image_path=db_model.image_path,
            uploader=db_model.uploader,
            image_id=db_model.id,
            file_size=db_model.file_size,
            hits=db_model.hits,
            tags=[Tag.from_db(t) for t in db_model.tags],
            rating=db_model.rating,
            created_date=db_model.created_date,
        )

    def __repr__(self):
        retstr = "<Image Model ("
        retstr += f" name={str(self.name)}"
        retstr += f" image_path={str(self.image_path)}"
        retstr += f" uploader={str(self.uploader)}"
        retstr += f" image_id={str(self.image_id)}"
        retstr += f" file_size={str(self.file_size)}"
        retstr += f" hits={str(self.hits)}"
        retstr += f" rating={str(self.rating)}"
        retstr += f" created_date={str(self.created_date)}"
        retstr += ')>'
        return retstr
