from functools import wraps

from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from vigilancia import services
from vigilancia.models import (Alarme, Dispositivo, Doente, IdempotencyKey,
                               Internamento, Leitura)
from .serializers import (AlarmeSerializer, DispositivoSerializer, DoenteSerializer,
                          InternamentoSerializer, ReadingSerializer)


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
                IdempotencyKey.objects.create(key=key, response=response.data)
            return response

    return wrapper


class DoenteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Doente.objects.none()          # só para o schema OpenAPI
    serializer_class = DoenteSerializer

    def get_queryset(self):
        return services.doentes_visiveis(self.request.user)


class InternamentoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Internamento.objects.none()
    serializer_class = InternamentoSerializer

    def get_queryset(self):
        return services.internamentos_acessiveis(self.request.user)

    @action(detail=True, methods=["post"])
    @idempotent_action
    def terminar(self, request, pk=None):
        internamento = services.dar_alta(self.get_object().pk)
        return Response({"status": "Internamento terminado com sucesso",
                         "alta": internamento.alta.isoformat()},
                        status=status.HTTP_200_OK)


class DispositivoViewSet(viewsets.ReadOnlyModelViewSet):
    # A ingestão (conta de serviço, sem perfil) consulta este endpoint por nº de série.
    queryset = Dispositivo.objects.select_related("internamento")
    serializer_class = DispositivoSerializer
    lookup_field = "numero_serie"
    lookup_value_regex = "[^/]+"


class ReadingViewSet(mixins.CreateModelMixin,
                     mixins.ListModelMixin,
                     viewsets.GenericViewSet):
    queryset = Leitura.objects.none()
    serializer_class = ReadingSerializer

    def get_queryset(self):
        return services.leituras_visiveis(self.request.user).order_by("-instante")

    def create(self, request, *args, **kwargs):
        is_many = isinstance(request.data, list)
        serializer = self.get_serializer(data=request.data, many=is_many)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response(
                {"detail": "Leituras já existentes (duplicadas ignoradas por idempotência)."},
                status=status.HTTP_200_OK)


class AlarmeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                    viewsets.GenericViewSet):
    queryset = Alarme.objects.none()
    serializer_class = AlarmeSerializer

    def get_queryset(self):
        return services.alarmes_visiveis(self.request.user).order_by("-criado_em")

    @action(detail=True, methods=["post"])
    @idempotent_action
    def reconhecer(self, request, pk=None):
        self.get_object()                    # 404 se o alarme não for visível a este utilizador
        try:
            alarme, _ = services.reconhecer_alarme(
                pk, request.user, ip=services.ip_do_pedido(request))
        except services.AlarmeJaReconhecido as e:
            return Response(
                {"detail": f"alarme já reconhecido por {getattr(e.por, 'username', '?')}"},
                status=status.HTTP_409_CONFLICT)
        # PermissionDenied (médico, outra enfermaria) propaga-se e o DRF converte em 403.
        return Response(AlarmeSerializer(alarme).data, status=status.HTTP_200_OK)
