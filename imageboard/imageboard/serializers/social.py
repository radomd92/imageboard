from . import JSONBuilder
from . import serialize_date
from ..model.social import Message as MessageModel
from ..model.social import User as UserModel


class User(JSONBuilder):
    def __init__(self, model):
        if not isinstance(model, UserModel):
            raise TypeError(f"Expected MessageModel, got {model.__class__}")

        super(User, self).__init__()
        self.model = model
        self.mapped_variables = [
            ('name', 'name'),
            ('registered', 'registered'),
            ('karma', 'karma'),
            ('privileges', 'privileges'),
            ('banned', 'banned'),
        ]

    @property
    def name(self):
        return self.model.name

    @property
    def registered(self):
        return serialize_date(self.model.registered)

    @property
    def karma(self):
        return self.model.karma

    @property
    def privileges(self):
        return self.model.privileges

    @property
    def banned(self):
        return self.model.banned


class Message(JSONBuilder):
    def __init__(self, model):
        if not isinstance(model, MessageModel):
            raise TypeError(f"Expected MessageModel, got {model.__class__}")

        super(Message, self).__init__()
        self.model = model
        self.mapped_variables = [
            ('message_id', 'message_id'),
            ('from_user', 'from_user'),
            ('text', 'text'),
            ('reply_to', 'reply_to'),
            ('message_date', 'message_date'),
        ]

    @property
    def message_id(self):
        return self.model.message_id

    @property
    def from_user(self):
        return ""

    @property
    def text(self):
        return self.model.text

    @property
    def reply_to(self):
        if self.model.reply_to is not None:
            return Message(self.model.reply_to)
        else:
            return None

    @property
    def message_date(self):
        if self.model.message_date is not None:
            return self.model.message_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return ''
