"""Image detail and authenticated mutation routes."""

from flask import Blueprint, redirect, render_template, request, url_for

from . import limiter
from .controllers.image import ImageController
from .permissions import admin_required
from .serializers.image import Image as ImageSerializer
from .serializers.social import Message as MessageSerializer

image_pages = Blueprint('images', __name__, url_prefix='/images')
images = ImageController()


@image_pages.get('/<int:image_id>/edit')
@admin_required
def edit_image(image_id):
    current_image = images.get_image_from_id(image_id)
    return render_template(
        'image_edit.html', title='Edit image', image=ImageSerializer(current_image).serialize()
    )


@image_pages.post('/<int:image_id>/edit/title')
@admin_required
def edit_image_title(image_id):
    images.set_image_title(image_id, request.form.get('title'))
    return redirect(url_for('images.image_detail', image_id=image_id), code=303)


@image_pages.post('/<int:image_id>/comment')
@limiter.limit('10 per minute')
def add_user_comment(image_id):
    images.add_comment(image_id, request.form.get('comment'), request.form.get('reply_to'))
    return redirect(url_for('images.image_detail', image_id=image_id), code=303)


@image_pages.post('/<int:image_id>/edit/tags')
@admin_required
def edit_image_tags(image_id):
    raw_tags = request.form.get('tags', '')
    images.set_image_tags(image_id, raw_tags.splitlines())
    return redirect(url_for('images.image_detail', image_id=image_id), code=303)


@image_pages.get('/<int:image_id>')
def image_detail(image_id):
    current_image = images.get_image_from_id(image_id)
    comments = images.load_comments(image_id)
    return render_template(
        'image.html',
        title=current_image.name,
        image=ImageSerializer(current_image).serialize(),
        comments=[MessageSerializer(comment).serialize() for comment in comments],
    )
