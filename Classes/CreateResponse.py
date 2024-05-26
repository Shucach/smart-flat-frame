from flask import jsonify


class CreateResponse:
    status = True
    message = None
    data = []

    def __init__(self):
        self.status = True
        self.message = None
        self.data = []

    def success(self):
        self.status = True
        return self.__to_json()

    def failed(self):
        self.status = False
        return self.__to_json()

    def set_message(self, message: str):
        self.message = message
        return self

    def set_data(self, data):
        self.data = data
        return self

    def __to_json(self):
        return jsonify({
            'success': self.status,
            'message': self.message,
            'data': self.data,
        }), 200
