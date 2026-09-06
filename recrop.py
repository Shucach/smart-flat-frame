"""
Одноразове приведення вже завантаженої галереї до поточних розмірів.

Перерізає повнорозмірні знімки під співвідношення рамки (9:16) і перебудовує
мініатюри. Запуск: `python3 recrop.py` (додай `--dry-run`, щоб лише подивитись).
"""
import os
import sys

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

from Classes.GalleryControl import GalleryControl
from Classes.ImageHelper import fit_to_size, normalise, save_jpeg


def main(dry_run: bool) -> int:
    load_dotenv()

    gallery = GalleryControl()
    target = gallery.frame_size[0] / gallery.frame_size[1]

    if not os.path.isdir(gallery.upload_url):
        print('Директорія галереї не існує:', gallery.upload_url)
        return 1

    os.makedirs(gallery.thumbnail_url, exist_ok=True)

    recropped = rebuilt = skipped = broken = 0

    for name in sorted(os.listdir(gallery.upload_url)):
        filepath = os.path.join(gallery.upload_url, name)

        if name.startswith('.') or not os.path.isfile(filepath):
            continue

        thumbnail_path = os.path.join(gallery.thumbnail_url, name + '.jpg')

        try:
            with Image.open(filepath) as source:
                needs_crop = abs(source.width / source.height - target) > 0.01
                picture = normalise(source)

                if needs_crop:
                    picture = fit_to_size(picture, *gallery.frame_size)

                    if not dry_run:
                        save_jpeg(picture, filepath, gallery.frame_quality)

                    print('переріз  {} {}x{}'.format(name, picture.width, picture.height))
                    recropped += 1

                if needs_crop or not os.path.isfile(thumbnail_path):
                    if not dry_run:
                        save_jpeg(
                            fit_to_size(picture, *gallery.thumbnail_size),
                            thumbnail_path,
                            gallery.thumbnail_quality,
                        )

                    rebuilt += 1
                elif not needs_crop:
                    skipped += 1
        except (UnidentifiedImageError, OSError, ValueError) as error:
            print('пропущено {}: {}'.format(name, error))
            broken += 1

    print('\nПерерізано: {}, мініатюр оновлено: {}, без змін: {}, пошкоджених: {}'.format(
        recropped, rebuilt, skipped, broken,
    ))

    if dry_run:
        print('(--dry-run: нічого не записано)')

    return 0


if __name__ == '__main__':
    sys.exit(main('--dry-run' in sys.argv))
