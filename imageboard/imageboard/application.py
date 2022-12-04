"""
Routes and views for the flask application.
"""
import _sha256
import io

import requests
from flask import render_template, send_file
from werkzeug.exceptions import ServiceUnavailable
from model.image import Image
from serializers.image import Image as ImageSerializer
from . import app



@app.route('/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Main page',
    )


def file_server_get_image(link):
    link = link.replace('$', '/')
    req = requests.get(f"{app.config.get('FILE_SERVER')}/{link}", stream=True, verify=False)
    if req.status_code != 200:
        raise ServiceUnavailable(f"Backend file server returned HTTP {req.status_code}")
    data = req.raw.read()
    return send_file(
        io.BytesIO(data),
        mimetype=req.headers.get('Content-Type', 'image/jpeg'),
        as_attachment=False,
        download_name=link.split('/')[-1]
    )


@app.route('/image_link/<link>')
def image_link(link):
    """Fetches images from image server. Link must replace / with $."""
    return file_server_get_image(link)


@app.route('/thumbnail/<link>/<size>')
def image_thumbnail(link, size):
    """Fetches images from image server. Link must replace / with $."""
    link = link.replace('$', '/') + f"§thumb§{size}"
    return file_server_get_image(link)


@app.route('/images/<image_id>')
def images(image_id=None):
    """Fetches an image by a given ID."""
    image = Image.from_id(image_id)
    return render_template(
        'image.html',
        title='Image',
        image=ImageSerializer(image).serialize()
    )


@app.route('/contact')
def contact():
    """Renders the contact page."""
    return render_template(
        'contact.html',
        title='Contact',
        message='Do not contact us. Speak to God and he shall answer.'
    )


@app.route('/about')
def about():
    """Renders the about page."""
    return render_template(
        'about.html',
        title='About the Paradise',
        message=''
    )
