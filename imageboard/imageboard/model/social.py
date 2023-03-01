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

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return True

    def get_id(self):
        return True


class Message(Model):
    def __init__(self, from_user: User, text: str, reply_to: int = None, message_id=None, message_date=None):
        self.from_user = from_user
        self.text = text
        self.reply_to = reply_to
        self.message_id = message_id
        self.message_date = message_date
        self.replies = []

    @staticmethod
    def from_db(message_db):
        message = Message(
            from_user=message_db.from_user,
            text=message_db.text,
            message_id=message_db.id,
            message_date=message_db.message_date
        )
        print(message_db.replies)
        message.replies = [Message.from_db(rpl) for rpl in message_db.replies]
        return message

    def __repr__(self):
        data = f"Message({self.message_id}, {self.text})" + " {"
        for r in self.replies:
            data += r.__repr__()

        data += '}'
        return data
