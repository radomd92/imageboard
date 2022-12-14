"""
Routes and views for the flask application.
"""

import io

import urllib3
from flask import render_template, request, send_file
from . import app
from .controllers.file_server import FileServerController
from .controllers.image import ImageController
from .serializers.image import Image as ImageSerializer


urllib3.disable_warnings()

file_server = FileServerController(app)
image = ImageController(app)


@app.route('/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Main page',
        images_needing_tags=image.get_image_needing_tags(),
        used_tags=image.get_used_tags(8),
    )


@app.route('/tags')
def get_used_tags():
    return render_template(
        'tag.html',
        title='Tag',
        images_from_tag=None,
        tags=image.get_used_tags(0),
    )


@app.route('/tags/<tag_name>')
def get_images_tags(tag_name=None):
    return render_template(
        'tag.html',
        title='Tag',
        tags=None,
        images_from_tag=image.get_images_with_tag(tag_name),
    )


@app.route('/search', methods=['POST', 'GET'])
def search():
    search_term = request.form.get('term')
    image_list = []
    if search_term is not None:
        image_list = image.get_search_results(search_term)

    return render_template(
        'search.html',
        title='Search results',
        images=image_list,
    )


@app.route('/image_link/<link>')
def image_link(link):
    """Fetches images from image server. Link must replace / with $."""
    data, mimetype = file_server.get_image(link)
    return send_file(
        io.BytesIO(data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=link.replace('$', '/').split('/')[-1]
    )


@app.route('/explore_recursive/')
@app.route('/explore_recursive/<link>')
def explore_recursively(link='', depth=7):
    """Fetches images from image server. Link must replace / with $."""

    links = file_server.get_link_as_json(link.replace('$', '/'))
    for link_item in links:
        link_item['link'] = link_item['name']
        if link:
            link_item['link'] = link + '$' + link_item['name']

        link_item['text'] = link_item['name']
        file_server.reference_image_depth(
            link_item['text'],
            link_item['link'],
            depth,
            link_item.get('size', None)
        )
        if depth > 0 and link_item['type'] == 'directory':
            print('    ' * depth + "Recursive call")
            try:
                return explore(link_item['link'], depth-1)
            except Exception as exc:
                print(exc)

    return render_template(
        'explorer.html',
        title='File explorer',
        links=links
    )


@app.route('/explore/')
@app.route('/explore/<link>')
def explore(link=''):
    """Fetches images from image server. Link must replace / with $."""

    links = file_server.get_link_as_json(link.replace('$', '/'))
    for link_item in links:
        link_item['link'] = link_item['name']
        if link:
            link_item['link'] = link + '$' + link_item['name']

        link_item['text'] = link_item['name']
        file_server.reference_image(
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

    data, mimetype = file_server.get_links(link)
    return send_file(
        io.BytesIO(data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=link.split('/')[-1]
    )


@app.route('/images/<image_id>/edit')
def edit_image(image_id=None):
    """Fetches an image by a given ID."""
    current_image = image.get_image_from_id(image_id)
    return render_template(
        'image_edit.html',
        title='Image',
        image=ImageSerializer(current_image).serialize()
    )


@app.route('/images/<image_id>/edit/title', methods=['POST'])
def edit_image_title(image_id=None):
    title = request.form.get('title')
    current_image = image.set_image_title(image_id, title)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Title edit successful. You'll be redirected shortly...",
    )


@app.route('/images/<image_id>/comment', methods=['POST'])
def add_user_comment(image_id=None):
    text = request.form.get('comment')
    reply_to = request.form.get('reply_to', None)
    current_image = image.add_comment(image_id, text, None)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Title edit successful. You'll be redirected shortly...",
    )


@app.route('/images/<image_id>/edit/tags', methods=['POST'])
def edit_image_tag(image_id=None):
    data = request.form.get('tags').split("\r\n")
    print(data)
    tags = [t.strip().lower() for t in data]

    current_image = image.get_image_from_id(image_id)
    image.set_image_tags(image_id, tags)
    return render_template(
        'redirect.html',
        redirect_to="/images/" + str(current_image.image_id),
        title=current_image.name,
        message="Tag edit successful. You'll be redirected shortly...",
    )


@app.route('/images/<image_id>')
def images(image_id=None):
    """Fetches an image by a given ID."""
    current_image = image.get_image_from_id(image_id)
    return render_template(
        'image.html',
        title='Image',
        image=ImageSerializer(current_image).serialize()
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
