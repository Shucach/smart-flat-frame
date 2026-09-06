import base64
import math
import os
import re
import time

from PIL import Image, UnidentifiedImageError

from Classes.CreateResponse import CreateResponse
from Classes.ImageHelper import fit_to_size, normalise, save_jpeg


class GalleryControl:
    """Owns the gallery directory: stores, lists and deletes the pictures the frame shows."""

    THUMBNAIL_DIRECTORY = '.thumbnails'
    MAX_PER_PAGE = 60

    def __init__(self):
        upload_url = os.getenv('UPLOAD_PATH')

        if not upload_url:
            raise ValueError('Upload directory dose not exist')

        self.upload_url = upload_url
        self.thumbnail_url = os.path.join(upload_url, self.THUMBNAIL_DIRECTORY)

        # The frame panel is portrait 9:16, and so is every tile in the web gallery,
        # so both the stored picture and its thumbnail are cut to that ratio.
        self.frame_size = (self.__setting('FRAME_WIDTH', 1080), self.__setting('FRAME_HEIGHT', 1920))
        self.thumbnail_size = (self.__setting('THUMBNAIL_WIDTH', 180), self.__setting('THUMBNAIL_HEIGHT', 320))
        self.frame_quality = self.__setting('FRAME_QUALITY', 88)
        self.thumbnail_quality = self.__setting('THUMBNAIL_QUALITY', 78)

    def store_images(self, request) -> CreateResponse:
        images = request.files.getlist('images')

        if not images:
            return CreateResponse().set_message('Images not exist').failed()

        os.makedirs(self.thumbnail_url, exist_ok=True)

        stored = []

        for image in images:
            name = self.__build_name(image.filename)

            try:
                with Image.open(image.stream) as source:
                    picture = fit_to_size(normalise(source), *self.frame_size)

                    save_jpeg(picture, os.path.join(self.upload_url, name), self.frame_quality)
                    save_jpeg(
                        fit_to_size(picture, *self.thumbnail_size),
                        self.__thumbnail_path(name),
                        self.thumbnail_quality,
                    )
            except (UnidentifiedImageError, OSError, ValueError):
                continue

            stored.append(name)

        if not stored:
            return CreateResponse().set_message('Images can not be processed').failed()

        return CreateResponse().set_data({'images': stored}).success()

    def delete_images(self, names) -> CreateResponse:
        names = [name for name in (self.__safe_name(name) for name in names) if name]

        if not names:
            return CreateResponse().set_message('Names not exist').failed()

        deleted = []

        for name in names:
            removed = False

            for filepath in (os.path.join(self.upload_url, name), self.__thumbnail_path(name)):
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    removed = True

            if removed:
                deleted.append(name)

        if not deleted:
            return CreateResponse().set_message('Images not found').failed()

        return CreateResponse().set_data({'images': deleted}).success()

    def list_images(self, request) -> CreateResponse:
        names = self.__gallery_names()
        total = len(names)

        per_page = min(max(1, request.args.get('prePage', type=int) or 5), self.MAX_PER_PAGE)
        max_page = max(1, math.ceil(total / per_page))
        page = min(max(1, request.args.get('page', type=int) or 1), max_page)

        offset = (page - 1) * per_page
        images = []

        for name in names[offset:offset + per_page]:
            preview = self.__preview(name)

            if preview is not None:
                images.append({'name': name, 'file': preview})

        res = {
            'images': images,
            'pagination': {
                'page': page,
                'prePage': per_page,
                'maxPage': max_page,
                'total': total,
            },
        }

        return CreateResponse().set_data(res).success()

    def __gallery_names(self):
        """Returns the gallery file names, newest first, ignoring the thumbnail directory."""
        if not os.path.isdir(self.upload_url):
            return []

        names = [
            name for name in os.listdir(self.upload_url)
            if not name.startswith('.') and os.path.isfile(os.path.join(self.upload_url, name))
        ]

        names.sort(key=lambda name: os.path.getmtime(os.path.join(self.upload_url, name)), reverse=True)

        return names

    def __preview(self, name):
        """Returns the cached thumbnail as a data URL, building it once if it is missing."""
        filepath = self.__thumbnail_path(name)

        if not os.path.isfile(filepath) and not self.__build_thumbnail(name):
            return None

        with open(filepath, 'rb') as handle:
            return 'data:image/jpeg;base64,' + base64.b64encode(handle.read()).decode('utf-8')

    def __build_thumbnail(self, name) -> bool:
        os.makedirs(self.thumbnail_url, exist_ok=True)

        try:
            with Image.open(os.path.join(self.upload_url, name)) as source:
                thumbnail = fit_to_size(normalise(source), *self.thumbnail_size)
                save_jpeg(thumbnail, self.__thumbnail_path(name), self.thumbnail_quality)
        except (UnidentifiedImageError, OSError, ValueError):
            return False

        return True

    def __thumbnail_path(self, name) -> str:
        return os.path.join(self.thumbnail_url, name + '.jpg')

    def __build_name(self, original) -> str:
        """Builds a unique, filesystem-safe `<timestamp>_<slug>.jpg` name for an upload."""
        stem = os.path.splitext(os.path.basename(original or ''))[0]
        stem = re.sub(r'[^A-Za-z0-9_-]+', '-', stem).strip('-')[:60] or 'image'

        name = '{}_{}.jpg'.format(round(time.time() * 1000), stem)
        suffix = 1

        while os.path.exists(os.path.join(self.upload_url, name)):
            name = '{}_{}-{}.jpg'.format(round(time.time() * 1000), stem, suffix)
            suffix += 1

        return name

    @staticmethod
    def __safe_name(name):
        """Keeps plain file names only, so a request can never reach outside the gallery."""
        name = str(name or '').strip()

        if not name or name.startswith('.') or name != os.path.basename(name):
            return None

        return name

    @staticmethod
    def __setting(key, fallback) -> int:
        try:
            value = int(os.getenv(key, fallback))
        except (TypeError, ValueError):
            return fallback

        return value if value > 0 else fallback
