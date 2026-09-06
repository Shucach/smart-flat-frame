from flask import Flask, jsonify, request
from dotenv import load_dotenv
import os

from Classes.CreateResponse import CreateResponse
from Classes.GalleryControl import GalleryControl

load_dotenv()
app = Flask(__name__)


def collect_names(request):
    """
    Reads the image names out of a request body.

    The Laravel client posts JSON, while a plain form post indexes the array as
    `images[0]`, `images[1]`, so both shapes are accepted.
    """
    payload = request.get_json(silent=True)

    if isinstance(payload, dict):
        names = payload.get('images')

        if isinstance(names, str):
            names = [names]

        if isinstance(names, list):
            return [str(name) for name in names if str(name).strip()]

    names = request.form.getlist('images') or request.form.getlist('images[]')

    if not names:
        names = [value for key, value in request.form.items(multi=True) if key.startswith('images[')]

    return [name for name in names if name.strip()]


# Routes
@app.before_request
def check_authorization():
    auth_key = request.headers.get('Authorization')

    if not auth_key:
        return jsonify({'error': 'Authorization key is required'}), 401

    if auth_key != os.getenv('AUTHKEY'):
        return jsonify({'error': 'Forbidden'}), 401


@app.route('/api/v1/upload-images', methods=['POST'])
def upload_images():
    if 'images' not in request.files:
        return CreateResponse().set_message('Images is required').failed()

    try:
        return GalleryControl().store_images(request)
    except ValueError as error:
        return CreateResponse().set_message(str(error)).failed()


@app.route('/api/v1/delete-images', methods=['POST'])
def delete_images():
    names = collect_names(request)

    if not names:
        return CreateResponse().set_message('Images is required').failed()

    try:
        return GalleryControl().delete_images(names)
    except ValueError as error:
        return CreateResponse().set_message(str(error)).failed()


@app.route('/api/v1/list-images', methods=['GET'])
def list_images():
    try:
        return GalleryControl().list_images(request)
    except ValueError as error:
        return CreateResponse().set_message(str(error)).failed()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7000, debug=True)
    #app.run(host='0.0.0.0', port=5000)
