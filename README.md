# imageboard

A simple imageboard written in Python using Flask. 

It works thanks to a nginx HTTP server serving a given folder as JSON data. A template for configuration has been given in in the nginx_file_server folder.
To check if it works, compiel and launch a nginx server with the [thumbnail module](https://nginx.org/en/docs/http/ngx_http_image_filter_module.html).
A simple authentication with username and password will restrict access to the nginx server. Remove it if not necessary.

# Feature list
- Image tagging
