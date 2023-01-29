# URL of the backend server. Serves nginx with autoindex on, serving filepaths in a JSON format.
FILE_SERVER = "https://192.168.1.1:8443/images/"

# Database URL used for the imageboard's tables
SQLALCHEMY_DATABASE_URI = 'postgresql://peter:pan@localhost:5432/imageboard'

# Local cache for imageboard thumbnails and images. Data is encrypted at rest.
CACHE_PATH = '/tmp/imageboard_cache'
