"""
Routes and views for the flask application.
"""
import _sha256
import io


from flask import render_template, send_file
from werkzeug.exceptions import ServiceUnavailable, BadRequest
from model.image import Image
from serializers.image import Image as ImageSerializer
from controllers import FileServerController
from . import app

controller = FileServerController(app)


@app.route('/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Main page',
    )


@app.route('/image_link/<link>')
def image_link(link):
    """Fetches images from image server. Link must replace / with $."""
    return controller.get_image(link)


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
        controller.reference_image(link_item['text'], link_item['link'])

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

    return controller.get_link(link)


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
