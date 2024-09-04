from flask import Flask, jsonify, request
from dotenv import load_dotenv
import os

from Classes.CreateResponse import CreateResponse
from Classes.GalleryControl import GalleryControl

load_dotenv()
app = Flask(__name__)


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
    if 'images' not in request.form:
        return CreateResponse().set_message('Images is required').failed()

    return GalleryControl().delete_images(request)


@app.route('/api/v1/list-images', methods=['GET'])
def list_images():
    return GalleryControl().list_images()


if __name__ == '__main__':
    #app.run(host='0.0.0.0', port=7000, debug=True)
    app.run(host='0.0.0.0', port=5000)
