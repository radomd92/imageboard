# imageboard

A simple imageboard written in Python using Flask. 

It works thanks to a nginx HTTP server serving a given folder as JSON data. A template for configuration has been given in in the nginx_file_server folder.
To check if it works, compile and launch a nginx server with the [thumbnail module](https://nginx.org/en/docs/http/ngx_http_image_filter_module.html).
A simple authentication with username and password will restrict access to the nginx server. Remove it if not necessary.

# Set-up

- First, set up the album with all your photos in a folder from which nginx will be serving.
- Compile Nginx with thumbnail module (mandatory) and  the XSLT module (optional, but also convenient)
- Edit the `nginx_file_server/nginx.conf.example` file and move / change file paths according to your Nginx setup.
- The imageboard configuration uses Nginx the `autoindex` ability to explore a given folder and present the folder's
  contents as a JSON list or a HTML page akin to your favourite file explorer.

## Backend: Using Nginx XSLT file explorer
**This is what you can use to explore your folders directly on the Nginx interface**

Uncomment these lines and changes the values to reflect your configuration:
```buildoutcfg
xslt_string_param title $1;
xslt_stylesheet /path/to/template.xslt;
```
Change the `autoindex_format` to `xml`
```buildoutcfg
autoindex_format xml;
```

Once you start nginx, you should find your images and be able to visualise them.

## Backend: Using Nginx JSON file explorer
**This is what the imageboard will be using to index images present on -- and served by -- your Nginx backend**

## Frontend: Configuration
In `imageboard/imageboard` folder; create `config.py` based on the `config_template.py`.

```
FILE_SERVER = "https://user:pass@localhost:8443/images/"
SQLALCHEMY_DATABASE_URI = 'postgresql://imageboard:password@localhost:5432/image_board'
```

## Frontend: Using flask

Create a virtual environment and install dependencies in `requirements.txt`

Launch the service by calling the `runserver.py`

## Frontend: Data storage

PostgreSQL is used as the default data storage engine. It does not store the images itself, but
rather the backend path of the images. Backend images and videos are discovered when the user 
goes through the exploration page.

To increase responsiveness, Redis and a filesystem cache are also used for the images. They are encrypted at rest on the filesystem using RSA (keys) and AES (data)

# Feature list
- Image tagging: associate tags with images.
