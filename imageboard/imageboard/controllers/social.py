from .. import db
from ..database import Message as MessageDatamodel
from ..controllers import BaseController


class Message(BaseController):
    def set_reply(self, message, reply):
        message.replies.append(reply)

    def get_from_id(self, message_id):
        from ..model.social import Message as MessageModel
        with self.app.app_context():
            message = db.session.query(MessageDatamodel).filter(MessageDatamodel.id == message_id).first()
            if not message:
                return None

            model = MessageModel(
                message.from_user,
                message.text,
                message_id=message_id,
                message_date=message.message_date,
            )
            if message.reply_to is not None:
                model.reply_to = message.reply_to

            return model
