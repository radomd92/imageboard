from . import JSONBuilder


class Tag(JSONBuilder):
    def __init__(self, tag):
        super(Tag, self).__init__()
        self.model = tag
        self.mapped_variables = [
            ('name', 'name'),
            ('images', 'images'),
        ]

    @property
    def name(self):
        return self.model.name

    @property
    def images(self):
        return self.model.images


class User(JSONBuilder):
    def __init__(self, user):
        super(User, self).__init__()
        self.model = user
        self.mapped_variables = [
            ('name', 'name'),
            ('registered', 'registered'),
            ('karma', 'karma'),
            ('privileges', 'privileges'),
            ('banned', 'banned'),
        ]

    @property
    def name(self) -> str:
        return self.model.name

    @property
    def registered(self) -> str:
        return self.model.registered

    @property
    def karma(self) -> str:
        return self.model.karma

    @property
    def privileges(self) -> str:
        return self.model.privileges

    @property
    def banned(self) -> str:
        return str(self.model.banned)


class Image(JSONBuilder):
    def __init__(self, image):
        super(Image, self).__init__()
        self.model = image
        self.mapped_variables = [
            ('image_id', 'image_id'),
            ('name', 'name'),
            ('created_date', 'created_date'),
            ('image_path', 'image_path'),
            # ('uploader', 'uploader'),
            ('tags', 'tags'),
            ('hits', 'hits'),
            ('rating', 'rating'),
            ('file_size', 'file_size'),
        ]

    @property
    def name(self) -> str:
        return self.model.name

    @property
    def image_id(self) -> str:
        return str(self.model.image_id)

    @property
    def hits(self):
        return self.model.hits

    @property
    def rating(self):
        return self.model.rating

    @property
    def file_size(self):
        return self.model.file_size

    @property
    def created_date(self) -> str:
        return self.model.created_date.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def image_path(self) -> str:
        return self.model.image_path.replace('/', '$')

    @property
    def uploader(self) -> User:
        return User(self.model.uploader)

    @property
    def tags(self) -> list:
        return [Tag(tag) for tag in self.model.tags]
