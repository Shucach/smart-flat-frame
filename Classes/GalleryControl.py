import base64
import os
import time

from PIL import Image

from Classes.CreateResponse import CreateResponse
from Classes.ImageHelper import crop_image_by_proportion


class GalleryControl:
    upload_url = None

    def __init__(self):
        self.upload_url = os.getenv('UPLOAD_PATH')
        if self.upload_url is None:
            raise ValueError("Upload directory dose not exist")

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

    def list_images(self) -> CreateResponse:
        images = []
        for filename in os.listdir(self.upload_url):
            filepath = os.path.join(self.upload_url, filename)
            with open(filepath, mode='rb') as file:
                images.append({
                    'name': filename,
                    'file': base64.b64encode(file.read()).decode('utf-8')
                })

        return CreateResponse().set_data(images).success()
