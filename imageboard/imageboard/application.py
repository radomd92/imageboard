"""
Routes and views for the flask application.
"""

import io

import urllib3
from flask import render_template, send_file

from . import app
from .controllers import FileServerController
from .serializers.image import Image as ImageSerializer


urllib3.disable_warnings()
controller = FileServerController(app)


@app.route('/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Main page',
        images_needing_tags=controller.get_image_needing_tags()
    )


@app.route('/image_link/<link>')
def image_link(link):
    """Fetches images from image server. Link must replace / with $."""
    data, mimetype = controller.get_image(link)
    return send_file(
        io.BytesIO(data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=link.split('/')[-1]
    )


@app.route('/explore/')
@app.route('/explore/<link>')
def explore(link=''):
    print('link:', link)
    """Fetches images from image server. Link must replace / with $."""

    links = controller.get_link_as_json(link.replace('$', '/'))

    for link_item in links:
        link_item['link'] = link_item['name']
        if link:
            link_item['link'] = link + '$' + link_item['name']

        link_item['text'] = link_item['name']
        controller.reference_image(
            link_item['text'],
            link_item['link'],
            link_item.get('size', None)
        )

    return render_template(
        'explorer.html',
        title='File explorer',
        links=links
    )


@app.route('/thumbnail/<link>/<size>')
def image_thumbnail(link, size):
    """Fetches images from image server. Link must replace / with $."""
    if link.lower().split('.')[-1] in ['mpg', 'mp4', 'wmv', 'mov', 'avi']:
        link = link.replace('$', '/') + f"§vthumb"
    else:
        link = link.replace('$', '/') + f"§thumb§{size}"

    data, mimetype = controller.get_links(link)
    return send_file(
        io.BytesIO(data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=link.split('/')[-1]
    )


@app.route('/images/<image_id>/edit')
def edit_image(image_id=None):
    """Fetches an image by a given ID."""
    image = controller.get_image_from_id(image_id)
    return render_template(
        'image_edit.html',
        title='Image',
        image=ImageSerializer(image).serialize()
    )


@app.route('/images/<image_id>/edit/title')
def edit_image_title(image_id=None):
    print("Editing image title")


@app.route('/images/<image_id>/edit/tags')
def edit_image_tag(image_id=None):
    print("Editing image tags")


@app.route('/images/<image_id>')
def images(image_id=None):
    """Fetches an image by a given ID."""
    image = controller.get_image_from_id(image_id)
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
