from . import JSONBuilder
from ..model.image import Image as ImageModel, Tag as TagModel


class Tag(JSONBuilder):
    def __init__(self, tag):
        if not isinstance(tag, TagModel):
            raise TypeError(f"Expected Tagmodel, got {tag.__class__}")

        super(Tag, self).__init__()
        self.model = tag
        self.mapped_variables = [
            ('name', 'name'),
        ]

    @property
    def name(self):
        return self.model.name


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
    def __init__(self, image: ImageModel):
        if not isinstance(image, ImageModel):
            raise TypeError(f"Expected ImageModel, got {image.__class__}")

        super(Image, self).__init__()
        self.model = image
        self.mapped_variables = [
            ('image_id', 'image_id'),
            ('name', 'name'),
            ('created_date', 'created_date'),
            ('image_path', 'image_path'),
            ('uploader', 'uploader'),
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
        if self.model.created_date is not None:
            return self.model.created_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return ""

    @property
    def image_path(self) -> str:
        return self.model.image_path.replace('/', '$')

    @property
    def uploader(self) -> str:
        return str(self.model.uploader)

    @property
    def tags(self) -> list:
        if self.model.tags is not None:
            return [Tag(tag) for tag in self.model.tags]
        else:
            return []
