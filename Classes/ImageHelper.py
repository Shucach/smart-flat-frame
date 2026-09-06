from PIL import Image, ImageOps

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1, where the constants live on the module.
    RESAMPLE = Image.LANCZOS


def normalise(img):
    """Applies the EXIF orientation and converts to RGB so the image can be saved as JPEG."""
    img = ImageOps.exif_transpose(img)

    if img.mode != 'RGB':
        img = img.convert('RGB')

    return img


def crop_to_aspect(img, width, height):
    """Centre-crops the image to the width/height ratio, keeping its resolution."""
    target = width / height
    source = img.width / img.height

    if abs(source - target) < 1e-9:
        return img

    if source > target:
        crop_width = round(img.height * target)
        offset = (img.width - crop_width) // 2
        box = (offset, 0, offset + crop_width, img.height)
    else:
        crop_height = round(img.width / target)
        offset = (img.height - crop_height) // 2
        box = (0, offset, img.width, offset + crop_height)

    return img.crop(box)


def fit_to_size(img, width, height):
    """Centre-crops to the target ratio and scales down to it, never upscaling a small source."""
    img = crop_to_aspect(img, width, height)

    if img.width <= width:
        return img

    return img.resize((width, height), RESAMPLE)


def save_jpeg(img, filepath, quality):
    img.save(filepath, format='JPEG', quality=quality, optimize=True, progressive=True)
