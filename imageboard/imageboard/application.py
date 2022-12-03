"""
Routes and views for the flask application.
"""
from flask import render_template
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


@app.route('/images/<image_id>')
def images(image_id=None):
    """Renders the home page."""
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
