"""
Routes and views for the flask application.
"""

import io

import urllib3
from flask import render_template, request, send_file
from . import app
from .controllers.file_server import FileServerController
from .controllers.image import ImageController, TagController
from .serializers.image import Image as ImageSerializer
from .utils import paginated
from .images import image_pages


urllib3.disable_warnings()

file_server = FileServerController(app)
image = ImageController(app)
tags = TagController(app)

app.register_blueprint(image_pages)


@app.route('/')
def home():
    """Renders the home page."""
    return render_template(
        'index.html',
        title='Main page',
        images_needing_tags=image.get_image_needing_tags(),
        used_tags=image.get_used_tags(8),
        most_viewed_tags_monthly=tags.get_monthly_viewed(),
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
@paginated
def get_images_tags(tag_name=None, page=0):
    return render_template(
        'tag.html',
        title='Tag',
        tags=None,
        page=page,
        images_from_tag=image.get_images_with_tag(tag_name, page),
    )


@app.route('/search', methods=['POST', 'GET'])
def search(page=0):
    search_term = request.args.get('term')
    image_list = []
    if search_term is not None:
        image_list = image.get_search_results(search_term, page)

    return render_template(
        'search.html',
        title='Search results',
        images=image_list,
        page=page,
    )


@app.route('/image_link/<link>')
def image_link(link):
    """Fetches images from image server. Link must replace / with $."""
    data, mimetype = file_server.get_image(link)
    image.register_hit(image.get_image_from_link(link).image_id)
    return send_file(
        io.BytesIO(data),
        mimetype=mimetype,
        as_attachment=False,
        download_name=link.replace('$', '/').split('/')[-1]
    )


@app.route('/explore_recursive/')
@app.route('/explore_recursive/<link>')
def explore_recursively(link='', current_depth=0, max_depth=7):

    links = file_server.get_link_as_json(link.replace('$', '/'))
    for link_item in links:
        link_item['link'] = link_item['name']
        if link:
            link_item['link'] = link + '$' + link_item['name']

        link_item['text'] = link_item['name']
        already_existing_image = file_server.reference_image_depth(
            link_item['text'],
            link_item['link'],
            current_depth,
            link_item.get('size', None)
        )
        link_item['image_db_data'] = None
        if already_existing_image is not None:
            link_item['image_db_data'] = ImageSerializer(already_existing_image).serialize()

        if max_depth > current_depth and link_item['type'] == 'directory':
            print('  ' * current_depth + "Recursive call {")
            try:
                explore_recursively(link_item['link'], current_depth+1, max_depth)
            except Exception as exc:
                print(exc)
            print('  ' * current_depth + "}")

    return render_template(
        'explorer.html',
        title='File explorer',
        links=links
    )


@app.route('/explore/')
@app.route('/explore/<link>')
def explore(link=''):
    links = file_server.get_link_as_json(link.replace('$', '/'))
    for link_item in links:
        link_item['link'] = link_item['name']
        if link:
            link_item['link'] = link + '$' + link_item['name']

        link_item['text'] = link_item['name']
        already_existing_image = file_server.reference_image(
            link_item['text'],
            link_item['link'],
            link_item.get('size', None)
        )
        link_item['image_db_data'] = None
        if already_existing_image is not None:
            link_item['image_db_data'] = ImageSerializer(already_existing_image).serialize()

    return render_template(
        'explorer.html',
        title='File explorer',
        links=links
    )


@app.route('/thumbnail/<link>/<size>')
def image_thumbnail(link, size):
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
