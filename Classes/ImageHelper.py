from PIL import Image


def crop_image_by_proportion(img, target_width_ratio, target_height_ratio):
    img_aspect = img.width / img.height
    target_aspect = target_width_ratio / target_height_ratio

    if img_aspect > target_aspect:
        new_height = img.height
        new_width = int(target_aspect * new_height)
        offset = (img.width - new_width) // 2
        img = img.crop((offset, 0, img.width - offset, img.height))
    else:
        new_width = img.width
        new_height = int(new_width / target_aspect)
        offset = (img.height - new_height) // 2
        img = img.crop((0, offset, img.width, img.height - offset))

    return img.resize((target_width_ratio * 100, target_height_ratio * 100), Image.ANTIALIAS)
