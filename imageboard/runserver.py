"""Development launcher. Use Gunicorn for production."""

import os

from imageboard import create_app


app = create_app()


if __name__ == '__main__':
    app.run(
        host=os.environ.get('SERVER_HOST', '127.0.0.1'),
        port=int(os.environ.get('SERVER_PORT', '8888')),
        debug=False,
    )
