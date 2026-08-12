from . import Model


class Message(Model):
    def __init__(self, from_user, text: str, reply_to: int = None, message_id=None, message_date=None):
        self.from_user = from_user
        self.text = text
        self.reply_to = reply_to
        self.message_id = message_id
        self.message_date = message_date
        self.replies = []

    @staticmethod
    def from_db(message_db):
        return Message(
            from_user=message_db.author.name if message_db.author else 'Deleted user',
            text=message_db.text,
            reply_to=message_db.reply_to,
            message_id=message_db.id,
            message_date=message_db.message_date,
        )
