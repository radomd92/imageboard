from . import Model


class Tag(Model):
    def __init__(self, name, images=0):
        self.name = name
        self.images = images

    @classmethod
    def from_name(cls, name):
        return Tag(name)


class User(Model):
    def __init__(self, name=None):
        self.name = name
        self.registered = None
        self.karma = None
        self.privileges = None
        self.banned = False

    @classmethod
    def from_id(cls, uploader_id):
        uploader = User()


class Image(Model):
    def __init__(self, name: str, uploader: User, image_path: str, created_date=None, tags=None):
        self.name = name
        self.created_date = created_date
        self.image_path = image_path
        self.uploader = uploader
        self.size = None
        self.file_size = None
        self.hits = 0
        self.rating = 0
        if tags is not None:
            self.tags = tags
        else:
            self.tags = []

    @classmethod
    def from_id(cls, image_id):
        return Image(
            name='Bogus',
            uploader=User('oteka'),
            image_path='/tmp/ika.jpg',
            tags=[Tag('ijeon', 10), Tag('mulajs', 1544)]
        )
