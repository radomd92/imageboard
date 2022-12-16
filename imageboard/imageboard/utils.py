from flask import request
from . import app


def paginated(f):
    def wrapper(*args, **kw):
        with app.app_context():
            page = int(request.args.get('page', '1'))
            page = max(1, page)

        return f(*args, **kw, page=page)

    return wrapper
