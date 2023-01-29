"""
This script runs the imageboard application using a development server.
"""

from os import environ
from imageboard.application import app
from gevent.pywsgi import WSGIServer


PORT = 8888

# if __name__ == '__main__':
#     HOST = environ.get('SERVER_HOST', '0.0.0.0')
#     try:
#         PORT = int(environ.get('SERVER_PORT', PORT))
#     except ValueError:
#         PORT = 8000
#     app.run(HOST, PORT)

if __name__ == '__main__':
    http_server = WSGIServer(('0.0.0.0', PORT), app)
    http_server.serve_forever()
