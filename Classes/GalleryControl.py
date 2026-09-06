import base64
import math
import os
import re
import time

from PIL import Image, UnidentifiedImageError

from Classes import MediaHelper
from Classes.CreateResponse import CreateResponse
from Classes.ImageHelper import fit_to_size, load_for, save_jpeg


class GalleryControl:
    """Owns the gallery directory: stores, lists and deletes what the frame shows.

    The gallery holds both stills and clips. A still is re-encoded to the exact
    panel size on the way in; a clip is stored as it arrives, because this board
    cannot re-encode video in any useful time and the conversion has already been
    done upstream. What it does instead is refuse a clip it could not play, and
    say why.
    """

    THUMBNAIL_DIRECTORY = '.thumbnails'
    MAX_PER_PAGE = 60

    def __init__(self):
        upload_url = os.getenv('UPLOAD_PATH')

        if not upload_url:
            raise ValueError('Upload directory dose not exist')

        self.upload_url = upload_url
        self.thumbnail_url = os.path.join(upload_url, self.THUMBNAIL_DIRECTORY)

        # The panel is a 1024x600 LCD turned on its side, so the frame is portrait
        # 600x1024 (~0.586) rather than 9:16. Pictures are stored at exactly that
        # size: the player then draws them 1:1, and the decoder can skip half of
        # every phone photo it reads, which this board needs.
        self.frame_size = (self.__setting('FRAME_WIDTH', 600), self.__setting('FRAME_HEIGHT', 1024))

        # Thumbnails follow the frame ratio, so the web gallery previews the same crop
        # the frame will show. A clip previews as a still lifted out of it.
        thumbnail_width = self.__setting('THUMBNAIL_WIDTH', 180)
        self.thumbnail_size = (
            thumbnail_width,
            self.__setting('THUMBNAIL_HEIGHT', self.__ratio_height(thumbnail_width)),
        )
        self.frame_quality = self.__setting('FRAME_QUALITY', 88)
        self.thumbnail_quality = self.__setting('THUMBNAIL_QUALITY', 78)

        # Clips arrive already cut to the frame, so these bounds only have to catch
        # what the GPU would choke on rather than shape anything.
        self.max_video_seconds = self.__setting('MAX_VIDEO_SECONDS', 300)
        self.max_video_pixels = (
            self.__setting('MAX_VIDEO_WIDTH', 1920) * self.__setting('MAX_VIDEO_HEIGHT', 1088)
        )

    def store_images(self, request) -> CreateResponse:
        images = request.files.getlist('images')

        if not images:
            return CreateResponse().set_message('Images not exist').failed()

        os.makedirs(self.thumbnail_url, exist_ok=True)

        stored = []
        rejected = []

        for image in images:
            try:
                if self.__is_video(image):
                    stored.append(self.__store_video(image))
                else:
                    stored.append(self.__store_picture(image))
            except ValueError as error:
                rejected.append({
                    'name': os.path.basename(image.filename or '') or 'upload',
                    'reason': str(error),
                })

        data = {'images': stored, 'rejected': rejected}

        if not stored:
            return CreateResponse().set_message('Images can not be processed').set_data(data).failed()

        return CreateResponse().set_data(data).success()

    def delete_images(self, names) -> CreateResponse:
        names = [name for name in (self.__safe_name(name) for name in names) if name]

        if not names:
            return CreateResponse().set_message('Names not exist').failed()

        deleted = []

        for name in names:
            if self.__discard(name):
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
                images.append({
                    'name': name,
                    'type': 'video' if MediaHelper.is_video_name(name) else 'image',
                    'file': preview,
                })

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

    def __store_picture(self, image) -> str:
        name = self.__build_name(image.filename, '.jpg', 'image')

        try:
            with Image.open(image.stream) as source:
                picture = fit_to_size(load_for(source, *self.frame_size), *self.frame_size)

                save_jpeg(picture, os.path.join(self.upload_url, name), self.frame_quality)
                save_jpeg(
                    fit_to_size(picture, *self.thumbnail_size),
                    self.__thumbnail_path(name),
                    self.thumbnail_quality,
                )
        except (UnidentifiedImageError, OSError, ValueError):
            self.__discard(name)
            raise ValueError('file could not be read as an image')

        return name

    def __store_video(self, video) -> str:
        """Stores a clip byte for byte, once the frame has agreed it can play it.

        Re-encoding is not an option here -- a single core at 700MHz would spend
        minutes on a short clip -- so a file the GPU cannot decode is refused
        outright rather than quietly stored and shown as a black screen.
        """
        name = self.__build_name(video.filename, '.mp4', 'video')
        filepath = os.path.join(self.upload_url, name)

        try:
            video.save(filepath)
        except OSError as error:
            self.__discard(name)
            raise ValueError('video could not be stored: {}'.format(error))

        try:
            described = MediaHelper.describe(filepath)
            reason = MediaHelper.reject_reason(
                described,
                self.max_video_seconds,
                self.max_video_pixels,
                self.frame_size[0] / self.frame_size[1],
            )

            if reason:
                raise ValueError(reason)

            if not self.__build_poster(name, described):
                raise ValueError('no still frame could be read out of the video')
        except ValueError:
            self.__discard(name)
            raise

        return name

    def __is_video(self, upload) -> bool:
        """Routes on the file's own header first, and only then on its name."""
        return MediaHelper.sniff_video(upload.stream) or MediaHelper.is_video_name(upload.filename)

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

        if MediaHelper.is_video_name(name):
            return self.__build_poster(name)

        try:
            with Image.open(os.path.join(self.upload_url, name)) as source:
                thumbnail = fit_to_size(load_for(source, *self.thumbnail_size), *self.thumbnail_size)
                save_jpeg(thumbnail, self.__thumbnail_path(name), self.thumbnail_quality)
        except (UnidentifiedImageError, OSError, ValueError):
            return False

        return True

    def __build_poster(self, name, described=None) -> bool:
        """Lifts a frame out of a clip and shrinks it into the gallery thumbnail."""
        filepath = os.path.join(self.upload_url, name)

        if described is None:
            try:
                described = MediaHelper.describe(filepath)
            except ValueError:
                return False

        still = self.__thumbnail_path(name) + '.still'

        try:
            moment = MediaHelper.poster_moment(described['duration'])

            if not MediaHelper.poster(filepath, still, moment):
                return False

            with Image.open(still) as source:
                save_jpeg(
                    fit_to_size(load_for(source, *self.thumbnail_size), *self.thumbnail_size),
                    self.__thumbnail_path(name),
                    self.thumbnail_quality,
                )
        except (UnidentifiedImageError, OSError, ValueError):
            return False
        finally:
            if os.path.isfile(still):
                os.remove(still)

        return True

    def __discard(self, name) -> bool:
        """Removes a gallery entry and its thumbnail, reporting whether anything went."""
        removed = False

        for filepath in (os.path.join(self.upload_url, name), self.__thumbnail_path(name)):
            if os.path.isfile(filepath):
                os.remove(filepath)
                removed = True

        return removed

    def __thumbnail_path(self, name) -> str:
        return os.path.join(self.thumbnail_url, name + '.jpg')

    def __build_name(self, original, extension, fallback) -> str:
        """Builds a unique, filesystem-safe `<timestamp>_<slug><extension>` name."""
        stem = os.path.splitext(os.path.basename(original or ''))[0]
        stem = re.sub(r'[^A-Za-z0-9_-]+', '-', stem).strip('-')[:60] or fallback

        name = '{}_{}{}'.format(round(time.time() * 1000), stem, extension)
        suffix = 1

        while os.path.exists(os.path.join(self.upload_url, name)):
            name = '{}_{}-{}{}'.format(round(time.time() * 1000), stem, suffix, extension)
            suffix += 1

        return name

    @staticmethod
    def __safe_name(name):
        """Keeps plain file names only, so a request can never reach outside the gallery."""
        name = str(name or '').strip()

        if not name or name.startswith('.') or name != os.path.basename(name):
            return None

        return name

    def __ratio_height(self, width) -> int:
        """Returns the height that puts `width` at the frame ratio."""
        return max(1, round(width * self.frame_size[1] / self.frame_size[0]))

    @staticmethod
    def __setting(key, fallback) -> int:
        try:
            value = int(os.getenv(key, fallback))
        except (TypeError, ValueError):
            return fallback

        return value if value > 0 else fallback
