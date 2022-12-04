from . import Model


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


class Message(Model):
    def __init__(self, from_user: User, text: str, reply_to: 'Message' = None):
        self.from_user = from_user
        self.text = text
        self.reply_to = reply_to

    @property
    def sent_date(self):
        return
