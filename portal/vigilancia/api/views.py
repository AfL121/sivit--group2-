from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.db import IntegrityError, transaction
from functools import wraps
from vigilancia.models import Doente, Internamento, Dispositivo, Leitura, IdempotencyKey
from .serializers import DoenteSerializer, InternamentoSerializer, DispositivoSerializer, ReadingSerializer


def idempotent_action(view_func):
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        
        if not key:
            return view_func(self, request, *args, **kwargs)
        
        # 1. Procurar a chave; se presente, retornar a resposta armazenada
        if IdempotencyKey.objects.filter(key=key).exists():
            stored = IdempotencyKey.objects.get(key=key)
            return Response(stored.response)
        
        # 2. Se não, executar e armazenar dentro da mesma transação
        with transaction.atomic():
            response = view_func(self, request, *args, **kwargs)
            
            if 200 <= response.status_code < 300:
                IdempotencyKey.objects.create(
                    key=key,
                    response=response.data
                )
            return response
            
    return wrapper

class DoenteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Doente.objects.all()
    serializer_class = DoenteSerializer

class InternamentoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Internamento.objects.select_related("doente").all()
    serializer_class = InternamentoSerializer

    @action(detail=True, methods=["post"])
    @idempotent_action  
    def terminar(self, request, pk=None):
        internamento = self.get_object()
        internamento.estado = "terminada" # ou o campo correspondente
        internamento.save()
        return Response({"status": "Internamento terminado com sucesso"}, status=status.HTTP_200_OK)

class DispositivoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dispositivo.objects.all()
    serializer_class = DispositivoSerializer

class ReadingViewSet(mixins.CreateModelMixin,
                     mixins.ListModelMixin,
                     viewsets.GenericViewSet):
    queryset = Leitura.objects.select_related("dispositivo").all().order_by("-instante")
    serializer_class = ReadingSerializer

    def create(self, request, *args, **kwargs):
        # Suporta tanto um único objeto como uma lista (lote) de leituras
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)

        try:
            # Tenta gravar os dados (respeitando a restrição UNIQUE para idempotência)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            # Se a restrição UNIQUE falhar (reenvio por timeout), tratamos de forma idempotente
            return Response(
                {"detail": "Leituras já existentes (duplicadas ignoradas por idempotência)."},
                status=status.HTTP_200_OK
            )

