"""Injeção de falhas para a experiência TP3-E2 (resposta perdida).

Desligado por omissão. Para ativar, definir no ambiente do portal:

    DROP_RESPONSE_PROB=0.3

Sem esta variável, o middleware não faz nada. Nunca deve ficar ligado fora
das experiências: simula um pedido que o servidor PROCESSOU mas cuja resposta
se perdeu, que é exatamente o cenário em que o cliente reenvia e a
idempotência tem de provar que não duplica nada.
"""
import os
import random


class DropResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Lido uma vez, no arranque do worker (configuração vem do ambiente).
        self.prob = float(os.environ.get("DROP_RESPONSE_PROB", "0"))

    def __call__(self, request):
        # O pedido é executado ATÉ AO FIM (a escrita acontece) e só depois a
        # resposta é "perdida". É por isso que se chama depois de get_response.
        response = self.get_response(request)
        if (self.prob
                and request.method == "POST"
                and "/api/v1/readings/" in request.path
                and random.random() < self.prob):
            raise ConnectionAbortedError("reply lost")
        return response