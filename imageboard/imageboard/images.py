from flask import render_template, request
from flask.blueprints import Blueprint

from . import app

from .controllers.file_server import FileServerController
from .controllers.image import ImageController
from .serializers.image import Image as ImageSerializer
from .serializers.social import Message as MessageSerializer


PAGE_NAME = 'images'
PAGE_PREFIX = '/' + PAGE_NAME


file_server = FileServerController(app)
image = ImageController(app)

image_pages = Blueprint(PAGE_NAME, __name__, template_folder='templates')


@image_pages.route(PAGE_PREFIX + '/<image_id>/edit')
def edit_image(image_id=None):
    """Fetches an image by a given ID."""
    current_image = image.get_image_from_id(image_id)
    return render_template(
        'image_edit.html',
        title='Image',
        image=ImageSerializer(current_image).serialize()
    )


@image_pages.route(PAGE_PREFIX + '/<image_id>/edit/title', methods=['POST'])
def edit_image_title(image_id=None):
    title = request.form.get('title')
    current_image = image.set_image_title(image_id, title)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Title edit successful. You'll be redirected shortly...",
    )


@image_pages.route(PAGE_PREFIX + '/<image_id>/comment', methods=['POST'])
def add_user_comment(image_id=None):
    text = request.form.get('comment')
    reply_to = request.form.get('reply_to', None)
    current_image = image.add_comment(image_id, text, reply_to)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Title edit successful. You'll be redirected shortly...",
    )


@image_pages.route(PAGE_PREFIX + '/<image_id>/edit/tags', methods=['POST'])
def edit_image_tag(image_id=None):
    data = request.form.get('tags').split("\r\n")
    tags = [t.strip().lower() for t in data]

    current_image = image.get_image_from_id(image_id)
    image.set_image_tags(image_id, tags)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Tag edit successful. You'll be redirected shortly...",
    )


@image_pages.route(PAGE_PREFIX + '/<image_id>')
def images(image_id=None):
    """Fetches an image by a given ID."""
    current_image = image.get_image_from_id(image_id)
    comments = image.load_comments(image_id)
    image.register_hit(image_id)
    return render_template(
        'image.html',
        title='Image',
        image=ImageSerializer(current_image).serialize(),
        comments=[MessageSerializer(comment).serialize() for comment in comments]
    )
