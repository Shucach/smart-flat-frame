#!/usr/bin/env python3
"""Paints the gallery onto the frame panel: stills into the framebuffer, clips through the GPU.

This replaced `fbi`, and the reason is video. fbi holds the console for as long as
it runs and reads its picture list once, at startup -- neither of which survives a
gallery with clips in it, because a clip needs the panel handed over to the GPU
and handed back on every pass. Writing the framebuffer directly needs no console
at all: the VT only has to be one nothing else prints to, which is what tty7
already was. The launch race `slideshowctl` used to retry five times went away
with fbi.

The gallery is re-read every pass, so an upload reaches the panel on its own.
`POST /api/v1/restart-slideshow` (a SIGHUP) only makes it immediate.
"""
import os
import signal
import subprocess
import sys
import threading

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1, where the constants live on the module.
    RESAMPLE = Image.LANCZOS

VIDEO_EXTENSIONS = ('.mp4', '.m4v', '.mov')
PICTURE_EXTENSIONS = ('.jpg', '.jpeg', '.png')
PLAYABLE = VIDEO_EXTENSIONS + PICTURE_EXTENSIONS


def setting(key, fallback) -> int:
    try:
        value = int(os.getenv(key, fallback))
    except (TypeError, ValueError):
        return fallback

    return value if value >= 0 else fallback


def log(message):
    sys.stdout.write('{}\n'.format(message))
    sys.stdout.flush()


class Panel:
    """The framebuffer, in the shape the panel actually reports."""

    def __init__(self, device):
        node = '/sys/class/graphics/{}'.format(os.path.basename(device))
        width, height = (int(part) for part in self.__read(node + '/virtual_size').split(','))

        self.device = device
        self.width = width
        self.height = height
        self.depth = int(self.__read(node + '/bits_per_pixel'))
        self.stride = int(self.__read(node + '/stride'))

        if self.depth != 32:
            raise SystemExit('framebuffer is {}bpp; this player writes 32bpp'.format(self.depth))

        # The line the panel scans out is wider than the line it shows (2432 bytes
        # against 600 visible pixels), so rows are padded one at a time instead of
        # the picture going down in a single blit.
        self.padding = b'\x00' * (self.stride - self.width * 4)
        self.dark = False

    def show(self, picture):
        self.__write(self.__pack(picture))
        self.dark = False

    def blank(self):
        if not self.dark:
            self.__write(b'\x00' * (self.stride * self.height))
            self.dark = True

    def frame(self, picture):
        """Turns any picture into one the size of the panel, on a black field."""
        picture = ImageOps.exif_transpose(picture)

        if picture.mode != 'RGB':
            picture = picture.convert('RGB')

        picture = self.__crop_to_ratio(picture)

        if picture.width > self.width:
            picture = picture.resize((self.width, self.height), RESAMPLE, reducing_gap=2.0)

        if picture.size == (self.width, self.height):
            return picture

        # A picture smaller than the panel keeps its own size rather than being
        # blown up -- the same rule the uploader follows -- and sits centred.
        field = Image.new('RGB', (self.width, self.height))
        field.paste(picture, ((self.width - picture.width) // 2, (self.height - picture.height) // 2))

        return field

    def __crop_to_ratio(self, picture):
        target = self.width / self.height
        source = picture.width / picture.height

        if abs(source - target) < 1e-9:
            return picture

        if source > target:
            crop = round(picture.height * target)
            offset = (picture.width - crop) // 2
            box = (offset, 0, offset + crop, picture.height)
        else:
            crop = round(picture.width / target)
            offset = (picture.height - crop) // 2
            box = (0, offset, picture.width, offset + crop)

        return picture.crop(box)

    def __pack(self, picture):
        # The panel reports `rgba 8/16,8/8,8/0,8/24` -- blue in the low byte, so
        # BGRX rather than RGBX, which is the difference between a photograph and
        # a blue-faced stranger.
        raw = picture.tobytes('raw', 'BGRX')

        if not self.padding:
            return raw

        line = self.width * 4

        return b''.join(raw[y * line:(y + 1) * line] + self.padding for y in range(self.height))

    def __write(self, buffer):
        with open(self.device, 'r+b') as handle:
            handle.write(buffer)

    @staticmethod
    def __read(path):
        with open(path) as handle:
            return handle.read().strip()


class Player:
    """Walks the gallery, giving each entry the panel for its slot."""

    def __init__(self):
        self.gallery = os.getenv('GALLERY', '/home/pi/images_api/images')
        self.panel = Panel(os.getenv('FRAMEBUFFER', '/dev/fb0'))

        self.picture_seconds = setting('DELAY', 60)
        self.video_seconds = setting('VIDEO_DELAY', self.picture_seconds)
        self.empty_seconds = setting('EMPTY_DELAY', 15)

        # Zero is right on this panel, which is worth stating because it looks
        # like an omission. The framebuffer layer is composited with a transform
        # (`vcgencmd dispmanx_list` shows `transform:3`), and omxplayer picks the
        # same one up on its own: asked for orientation 0 its layer comes out
        # `transform:3` too, matching the stills exactly. The knob is here for a
        # panel where that does not hold.
        self.orientation = setting('VIDEO_ORIENTATION', 0)

        self.wake = threading.Event()
        self.stopping = False
        self.reloading = False
        self.video = None

    def run(self):
        while not self.stopping:
            entries = self.__entries()

            if not entries:
                self.panel.blank()
                self.wait(self.empty_seconds)
                continue

            self.reloading = False
            stamp = self.__stamp()

            for filepath in entries:
                if self.stopping or self.reloading or self.__stamp() != stamp:
                    break

                self.__play(filepath)

    def wait(self, seconds):
        """Sleeps out a slot, unless something asks the player to move on early."""
        self.wake.wait(seconds)
        self.wake.clear()

    def stop(self, *_):
        self.stopping = True
        self.wake.set()

    def reload(self, *_):
        self.reloading = True
        self.wake.set()

    def shutdown(self):
        self.__stop_video()

    def __play(self, filepath):
        if os.path.splitext(filepath)[1].lower() in VIDEO_EXTENSIONS:
            self.__play_video(filepath)
        else:
            self.__show_picture(filepath)

    def __show_picture(self, filepath):
        try:
            with Image.open(filepath) as source:
                # Let the JPEG decoder halve the picture as it reads: the gallery
                # already stores everything at panel size, but a hand-dropped file
                # can be a full phone photograph, and this board feels the difference.
                box = max(self.panel.width, self.panel.height)

                try:
                    source.draft('RGB', (box, box))
                except (AttributeError, ValueError):
                    pass

                picture = self.panel.frame(source)
        except (UnidentifiedImageError, OSError, ValueError) as error:
            log('skipping {}: {}'.format(os.path.basename(filepath), error))
            return

        self.panel.show(picture)
        self.wait(self.picture_seconds)

    def __play_video(self, filepath):
        """Hands the clip to the GPU and lets it loop until the slot is up.

        The looping is omxplayer's own, so a five-second clip fills a sixty-second
        slot without this process doing anything: a short clip behaves like a still
        that happens to move, and the gallery moves on when the slot ends.
        """
        self.panel.blank()

        # `stretch` rather than `fill` or `letterbox`, and the reason is that
        # omxplayer measures the clip against the panel's unrotated 1024x600
        # shape. `fill` answers that by cropping the middle 600x449 band out of
        # the clip and blowing it up; `letterbox` answers it by shrinking the clip
        # into a 263-pixel strip down the centre. `stretch` maps the whole clip
        # onto the whole panel -- which, for a clip that already arrived at the
        # frame's own ratio, is an exact 1:1 copy and no stretching at all. The
        # uploader enforces that ratio for exactly this reason.
        command = [
            'omxplayer', '--loop', '--no-osd', '--no-keys',
            '--aspect-mode', 'stretch', '--layer', '1',
            '--orientation', str(self.orientation),
            '-n', '-1',                       # no audio track: the frame has no speaker
            filepath,
        ]

        try:
            self.video = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            log('cannot play {}: {}'.format(os.path.basename(filepath), error))
            self.wait(self.picture_seconds)
            return

        self.wait(self.video_seconds)
        self.__stop_video()

    def __stop_video(self):
        process, self.video = self.video, None

        if process is None or process.poll() is not None:
            return

        # /usr/bin/omxplayer is a shell wrapper around omxplayer.bin, so signalling
        # the child alone would leave the player itself sitting on the panel.
        for sign in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(process.pid), sign)
            except OSError:
                return

            try:
                process.wait(timeout=5)
                return
            except subprocess.TimeoutExpired:
                continue

    def __entries(self):
        try:
            names = sorted(
                name for name in os.listdir(self.gallery)
                if not name.startswith('.')
                and os.path.splitext(name)[1].lower() in PLAYABLE
                and os.path.isfile(os.path.join(self.gallery, name))
            )
        except OSError as error:
            log('cannot read {}: {}'.format(self.gallery, error))
            return []

        # Names open with the upload timestamp, so sorting by name is sorting by
        # age -- the order the gallery had under fbi's `find | sort`.
        return [os.path.join(self.gallery, name) for name in names]

    def __stamp(self):
        """The gallery's own mtime, which moves whenever a file is added or removed."""
        try:
            return os.stat(self.gallery).st_mtime
        except OSError:
            return 0


def claim_pidfile(path):
    """Records the running player, and hands back a callable that clears the record.

    `slideshowctl` used to find the player with `pgrep -f` on the script path,
    which matches anything that merely *mentions* the path -- a shell running a
    deployment command was enough to convince it the frame was already up. The
    player naming itself is the only answer that cannot be fooled.
    """
    try:
        with open(path, 'w') as handle:
            handle.write('{}\n'.format(os.getpid()))
    except OSError as error:
        log('cannot write {}: {}'.format(path, error))
        return lambda: None

    def release():
        try:
            os.remove(path)
        except OSError:
            pass

    return release


def prepare_console(vt):
    """Puts the panel on a VT nothing prints to, and stops it going to sleep.

    The player owns no terminal, but the console driver still paints over the
    framebuffer, so the frame needs a VT with no getty on it and no kernel
    messages arriving.
    """
    subprocess.run(['chvt', str(vt)], stderr=subprocess.DEVNULL, check=False)

    try:
        with open('/dev/tty{}'.format(vt), 'wb') as console:
            subprocess.run(
                ['setterm', '--cursor', 'off', '--blank', '0', '--powerdown', '0', '--msg', 'off'],
                stdout=console, stderr=subprocess.DEVNULL, check=False,
            )
    except OSError:
        pass


def main():
    player = Player()

    signal.signal(signal.SIGTERM, player.stop)
    signal.signal(signal.SIGINT, player.stop)
    signal.signal(signal.SIGHUP, player.reload)

    prepare_console(setting('VT', 7))
    release = claim_pidfile(os.getenv('PIDFILE', '/run/framecast.pid'))

    log('frame {}x{} at {}bpp, gallery {}'.format(
        player.panel.width, player.panel.height, player.panel.depth, player.gallery,
    ))

    try:
        player.run()
    finally:
        player.shutdown()
        release()

    return 0


if __name__ == '__main__':
    sys.exit(main())
