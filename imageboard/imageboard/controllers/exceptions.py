from werkzeug.exceptions import NotFound, BadRequest


class CacheError(IOError):
    pass


class NoSuchImageException(NotFound):
    def __init__(self, message, label='NO_IMAGE'):
        super(NoSuchImageException, self).__init__(f'[{label}] ' + str(message))


class PageSaveError(BadRequest):
    def __init__(self, message, label='PAGE_SAVE_ERROR'):
        super(PageSaveError, self).__init__(f'[{label}] ' + str(message))

