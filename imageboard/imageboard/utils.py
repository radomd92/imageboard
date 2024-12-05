from flask import request
from . import app


def paginated(function):
    def wrapper(*args, **kw):
        with app.app_context():
            page = int(request.args.get('page', '1'))
            page = max(1, page)

        return function(*args, **kw, page=page)

    wrapped_function = wrapper
    wrapped_function.__name__ = f'{function.__name__}_wrapper'
    return wrapped_function

