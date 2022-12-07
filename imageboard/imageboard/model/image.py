from . import Model
from .social import User


class Tag(Model):
    def __init__(self, name, images=0):
        self.name = name
        self.images = images

    @classmethod
    def from_name(cls, name):
        return Tag(name)


class Image(Model):
    def __init__(self, name: str, image_path: str, uploader: User, image_id=None, file_size=0, hits=0, rating=0, created_date=None,
                 tags=None):
        self.name = name
        self.created_date = created_date
        self.image_path = image_path
        self.uploader = uploader
        self.image_id = image_id
        self.file_size = file_size
        self.hits = hits
        self.rating = rating
        if tags is not None:
            self.tags = tags
        else:
            self.tags = []

    @classmethod
    def from_db(cls, db_model):
        print(db_model.id)
        image = Image(
            image_id=db_model.id,
            name=db_model.name,
            created_date=db_model.created_date,
            image_path=db_model.image_path,
            uploader=db_model.uploader,
            file_size=db_model.file_size,
            hits=db_model.hits,
            rating=db_model.rating
        )
        return image
