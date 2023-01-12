"""
This script runs the imageboard application using a development server.
"""

from os import environ
from imageboard.application import app

# if __name__ == '__main__':
#     HOST = environ.get('SERVER_HOST', '0.0.0.0')
#     try:
#         PORT = int(environ.get('SERVER_PORT', '8000'))
#     except ValueError:
#         PORT = 8000
#     app.run(HOST, PORT)
from gevent.pywsgi import WSGIServer

if __name__ == '__main__':
    http_server = WSGIServer(('0.0.0.0', 8888), app)
    http_server.serve_forever()
