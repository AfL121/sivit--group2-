import random

class DropResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Interceta apenas pedidos para o endpoint de leituras
        if "/api/v1/readings/" in request.path and random.random() < 0.3:
            raise ConnectionAbortedError("reply lost")
        return response