"""The video half of the gallery: what the panel can play, and a still from it.

The frame decodes H.264 in the GPU and nothing else. BCM2835 has no HEVC block at
all, and its MPEG-2 and VC-1 licences are not bought, so `vcgencmd codec_enabled`
answers `disabled` for both. Whatever the user filmed therefore has to be
converted *before* it reaches this box; the conversion happens upstream and this
module only tells a file the frame can play apart from one it cannot, and pulls a
poster frame out of it for the web gallery.

The checks are deliberately specific: rejecting an upload with "video is HEVC
(H.265); the frame only plays H.264" is worth a great deal more to whoever is
looking at the upload form than a silent skip.
"""
import json
import os
import subprocess

FFPROBE = os.getenv('FFPROBE_BIN', 'ffprobe')
FFMPEG = os.getenv('FFMPEG_BIN', 'ffmpeg')

PROBE_TIMEOUT = 60
POSTER_TIMEOUT = 120

VIDEO_EXTENSIONS = ('.mp4', '.m4v', '.mov')

# What the GPU on this board will actually take. Profiles above High and levels
# above 4.2 decode as a green mess or not at all, and the hardware path only
# handles 8-bit 4:2:0.
SUPPORTED_CODEC = 'h264'
SUPPORTED_PROFILES = ('constrained baseline', 'baseline', 'main', 'high')
SUPPORTED_PIXEL_FORMATS = ('yuv420p', 'yuvj420p')
MAX_LEVEL = 42

# Spelled out for the rejection message, because "h265" means nothing to a user.
CODEC_NAMES = {
    'hevc': 'HEVC (H.265)',
    'h265': 'HEVC (H.265)',
    'vp9': 'VP9',
    'vp8': 'VP8',
    'av1': 'AV1',
    'mpeg4': 'MPEG-4 Part 2',
    'mpeg2video': 'MPEG-2',
    'vc1': 'VC-1',
}


def is_video_name(filename) -> bool:
    return os.path.splitext(str(filename or ''))[1].lower() in VIDEO_EXTENSIONS


def sniff_video(stream) -> bool:
    """Reports whether the stream opens with an ISO base media (MP4/MOV) header.

    Routing on the file's own bytes rather than on the name it arrived under means
    a video still lands in the video path when the client sends it as `clip.bin`.
    """
    try:
        position = stream.tell()
        header = stream.read(12)
        stream.seek(position)
    except (OSError, ValueError, AttributeError):
        return False

    return len(header) >= 12 and header[4:8] == b'ftyp'


def describe(filepath) -> dict:
    """Returns what the frame needs to know about a video, or raises `ValueError`."""
    process = __run(
        [FFPROBE, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', filepath],
        PROBE_TIMEOUT,
    )

    if process.returncode != 0:
        raise ValueError('file could not be read as a video')

    try:
        payload = json.loads(process.stdout.decode('utf-8', 'replace'))
    except ValueError:
        raise ValueError('file could not be read as a video')

    track = next(
        (item for item in payload.get('streams') or [] if item.get('codec_type') == 'video'),
        None,
    )

    if track is None:
        raise ValueError('file carries no video track')

    return {
        'codec': str(track.get('codec_name') or '').lower(),
        'profile': str(track.get('profile') or '').lower(),
        'level': __number(track.get('level')),
        'pixel_format': str(track.get('pix_fmt') or '').lower(),
        'width': int(__number(track.get('width'))),
        'height': int(__number(track.get('height'))),
        'duration': __number((payload.get('format') or {}).get('duration')),
    }


def reject_reason(video: dict, max_seconds: int, max_pixels: int, frame_ratio: float = 0.0):
    """Returns why the frame cannot play this video, or `None` when it can."""
    codec = video['codec']

    if codec != SUPPORTED_CODEC:
        return 'video is {}; the frame only plays H.264'.format(CODEC_NAMES.get(codec, codec or 'an unknown codec'))

    if video['profile'] and video['profile'] not in SUPPORTED_PROFILES:
        return 'H.264 {} profile is above what the frame decodes (High and below)'.format(video['profile'])

    # ffprobe reports a negative level when the container does not carry one, which
    # is not itself a reason to refuse the file.
    if video['level'] > MAX_LEVEL:
        return 'H.264 level {:.1f} is above the frame limit of 4.2'.format(video['level'] / 10)

    if video['pixel_format'] and video['pixel_format'] not in SUPPORTED_PIXEL_FORMATS:
        return 'pixel format {} is not 8-bit 4:2:0, which is all the GPU decodes'.format(video['pixel_format'])

    if not video['width'] or not video['height']:
        return 'video track has no usable frame size'

    if video['width'] * video['height'] > max_pixels:
        return 'frame size {}x{} is larger than the frame decodes'.format(video['width'], video['height'])

    # The player hands the clip to the GPU stretched across the whole panel,
    # because omxplayer measures a clip against the panel's unrotated shape and
    # both of its fitting modes get it wrong here. That is an exact copy for a
    # clip already at the panel's ratio and a funhouse mirror for anything else,
    # so the ratio is a requirement rather than a preference. Cropping it here is
    # not an option: this board cannot re-encode video in any useful time.
    if frame_ratio and video['height']:
        ratio = video['width'] / video['height']

        if abs(ratio - frame_ratio) > 0.02:
            return (
                'frame is {}x{}, a ratio of {:.3f}; the panel needs {:.3f} '
                '(600x1024), so the clip has to be cropped before it is uploaded'
            ).format(video['width'], video['height'], ratio, frame_ratio)

    if max_seconds and video['duration'] > max_seconds:
        return 'clip is {:.0f}s long; the limit is {}s'.format(video['duration'], max_seconds)

    return None


def poster(filepath, target, when=None) -> bool:
    """Writes one full-size still out of the video, for the gallery to shrink."""
    # A frame from a little way in beats frame zero: clips very often open on a
    # black or half-exposed frame, which would make the whole gallery look broken.
    if when is None:
        when = 1.0

    process = __run(
        [FFMPEG, '-v', 'error', '-y', '-ss', '{:.3f}'.format(max(0.0, when)),
         '-i', filepath, '-frames:v', '1', '-q:v', '2', '-f', 'image2', target],
        POSTER_TIMEOUT,
    )

    return process.returncode == 0 and os.path.isfile(target) and os.path.getsize(target) > 0


def poster_moment(duration) -> float:
    """Picks how far into the clip the poster frame comes from."""
    return min(1.0, duration / 2) if duration and duration > 0 else 0.0


def __run(command, timeout):
    try:
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError('video took too long to inspect')
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('video tooling is unavailable: {}'.format(error))


def __number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
