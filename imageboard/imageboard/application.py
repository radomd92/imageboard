"""Main browsing and media routes."""

from flask import Blueprint, Response, render_template, request
from flask_login import current_user

from . import limiter
from .controllers.exceptions import NoSuchImageException
from .controllers.file_server import FileServerController, canonical_media_path, is_supported_media
from .controllers.image import ImageController, TagController
from .permissions import admin_required
from .serializers.image import Image as ImageSerializer

main_pages = Blueprint('main', __name__)
file_server = FileServerController()
images = ImageController()
tags = TagController()


def page_number():
    try:
        return max(1, int(request.args.get('page', '1')))
    except ValueError:
        return 1


@main_pages.get('/')
def home():
    return render_template(
        'index.html',
        title='Library',
        images_needing_tags=[ImageSerializer(model) for model in images.get_image_needing_tags()],
        used_tags=images.get_used_tags(8),
        most_viewed_tags_monthly=tags.get_monthly_viewed(),
    )


@main_pages.get('/tags')
def get_used_tags():
    return render_template(
        'tag.html', title='Tags', images_from_tag=None, tags=images.get_used_tags(0), page=1
    )


@main_pages.get('/tags/<tag_name>')
def get_images_tags(tag_name):
    page = page_number()
    return render_template(
        'tag.html',
        title='Tag',
        tags=None,
        page=page,
        images_from_tag=images.get_images_with_tag(tag_name, page),
    )


@main_pages.get('/search')
def search():
    page = page_number()
    search_term = request.args.get('term', '')
    image_list = images.get_search_results(search_term, page)
    return render_template(
        'search.html',
        title='Search results',
        term=search_term,
        images=[ImageSerializer(model) for model in image_list],
        page=page,
    )


@main_pages.get('/media/<path:link>')
@limiter.limit('120 per minute')
def media(link):
    canonical = canonical_media_path(link)
    image_model = images.get_image_from_link(canonical)
    upstream, mimetype, filename = file_server.open_media(canonical)
    images.register_hit(image_model.image_id)
    return _stream_response(upstream, mimetype, filename, cache_seconds=0)


@main_pages.get('/thumbnail/<path:link>/<size>')
@limiter.limit('300 per minute')
def thumbnail(link, size):
    canonical = canonical_media_path(link)
    images.get_image_from_link(canonical)
    upstream, mimetype, filename = file_server.open_media(canonical, thumbnail_size=size)
    return _stream_response(upstream, mimetype, filename, cache_seconds=86400)


def _stream_response(upstream, mimetype, filename, cache_seconds):
    response = Response(file_server.iter_media(upstream), mimetype=mimetype, direct_passthrough=True)
    response.headers['Content-Disposition'] = 'inline'
    response.headers['Cache-Control'] = (
        f'private, max-age={cache_seconds}' if cache_seconds else 'private, no-store'
    )
    response.headers['Content-Length'] = upstream.headers.get('Content-Length', '')
    if not response.headers['Content-Length']:
        response.headers.pop('Content-Length', None)
    return response


@main_pages.get('/explore')
@main_pages.get('/explore/<path:link>')
@admin_required
@limiter.limit('30 per minute')
def explore(link=''):
    parent = canonical_media_path(link, allow_empty=True)
    listing = file_server.get_directory(parent)
    links = []
    for item in listing:
        item_link = f'{parent}${item["name"]}' if parent else item['name']
        item['link'] = canonical_media_path(item_link)
        item['text'] = item['name']
        item['supported'] = item['type'] == 'directory' or is_supported_media(item['link'])
        item['image_db_data'] = None
        if item['type'] == 'file' and item['supported']:
            try:
                model = images.get_image_from_link(item['link'])
                item['image_db_data'] = ImageSerializer(model).serialize()
            except NoSuchImageException:
                pass
        links.append(item)
    return render_template('explorer.html', title='Media explorer', links=links, current_path=parent)


@main_pages.post('/explore/index')
@admin_required
@limiter.limit('60 per minute')
def index_media():
    link = canonical_media_path(request.form.get('link'))
    name = request.form.get('name', '')
    size = request.form.get('size')
    image = file_server.reference_image(name, link, size, uploader_id=current_user.id)
    if image is None:
        return render_template('error.html', title='Unsupported media', error='Unsupported media type.'), 400
    return render_template(
        'redirect.html',
        redirect_to=f'/images/{image.image_id}',
        title=image.name,
        message='Media indexed successfully.',
    )


@main_pages.get('/about')
def about():
    return render_template('about.html', title='About', message='A private, self-hosted media library.')
