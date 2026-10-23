from functools import wraps
from django.db import transaction
from rest_framework.response import Response
from .models import IdempotencyKey

def idempotent_action(view_func):
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        # O cliente envia a chave no cabeçalho HTTP 'Idempotency-Key'
        key = request.headers.get("Idempotency-Key")
        
        # Se não for enviada chave, executa normalmente a view
        if not key:
            return view_func(self, request, *args, **kwargs)
        
        # 1. Verificar se a chave já existe; se sim, devolver a resposta guardada anteriormente
        if IdempotencyKey.objects.filter(key=key).exists():
            saved_record = IdempotencyKey.objects.get(key=key)
            return Response(saved_record.response)
        
        # 2. Se não existir, executar e guardar dentro da mesma transação atómica
        with transaction.atomic():
            response = view_func(self, request, *args, **kwargs)
            
            # Apenas guardamos respostas bem-sucedidas (ex: 200 OK ou 201 Created)
            if 200 <= response.status_code < 300:
                IdempotencyKey.objects.create(
                    key=key,
                    response=response.data
                )
            return response
            
    return wrapper