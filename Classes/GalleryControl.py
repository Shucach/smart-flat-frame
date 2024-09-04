import base64
import math
import os
import time
from io import BytesIO

from PIL import Image

from Classes.CreateResponse import CreateResponse
from Classes.ImageHelper import crop_image_by_proportion, crop_image_to_fixed_size


class GalleryControl:
    upload_url = None

    def __init__(self):
        self.upload_url = os.getenv('UPLOAD_PATH')
        if self.upload_url is None:
            raise ValueError("Upload directory dose not exist")

    #TODO: нарізати мініатюри, невивозе мережа.
    def store_images(self, request) -> CreateResponse:
        if not os.path.exists(self.upload_url):
            os.makedirs(self.upload_url)

        images = request.files.getlist('images')

        if not images:
            return CreateResponse().set_message('Images not exist').failed()

        for image in images:
            file_name = str(round(time.time() * 1000)) + '_' + image.filename
            filepath = os.path.join(self.upload_url, file_name)
            image.save(filepath)

            img = Image.open(filepath)
            cropped_img = crop_image_by_proportion(img, 9, 16)
            cropped_img.save(filepath)

        return CreateResponse().success()

    # TODO: видаляти мініатюри.
    def delete_images(self, request) -> CreateResponse:
        names = request.form.getlist('images')
        names = list(filter(lambda x: x.strip(), names))

        if not names:
            return CreateResponse().set_message('Names not exist').failed()

        for name in names:
            filepath = os.path.join(self.upload_url, name)
            if os.path.exists(filepath):
                os.remove(filepath)

        return CreateResponse().success()

    def list_images(self, request) -> CreateResponse:
        images = []

        allList = os.listdir(self.upload_url)

        page = int(request.args.get('page', 1))
        prePage = int(request.args.get('prePage', 5))
        maxPage = math.ceil(len(allList) / prePage)

        if page >= maxPage:
            page = maxPage

        if page > 1:
            pageData = allList[prePage:prePage + prePage]
        else:
            pageData = allList[:prePage]

        for filename in pageData:
            filepath = os.path.join(self.upload_url, filename)

            with Image.open(filepath) as img:
                cropped_img = crop_image_to_fixed_size(img, 100, 150)

                buffered = BytesIO()
                cropped_img.save(buffered, format="JPEG")

                images.append({
                    'name': filename,
                    'file': 'data:image/jpeg;base64,' + base64.b64encode(buffered.getvalue()).decode('utf-8')
                })

                buffered.close()

        res = {
            'images': images,
            'pagination': {
                'page': page,
                'prePage': prePage,
                'maxPage': maxPage,
            }
        }

        return CreateResponse().set_data(res).success()
