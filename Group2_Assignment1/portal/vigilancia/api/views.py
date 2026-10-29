

from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets

from rest_framework.response import Response

from vigilancia import services
from vigilancia.models import (Alarme, Dispositivo, Doente, IdempotencyKey,
                               Internamento, Leitura)
from .serializers import (AlarmeSerializer, DispositivoSerializer, DoenteSerializer,
                          InternamentoSerializer, ReadingSerializer)


def resposta_guardada(chave):
    """Devolve a resposta guardada para esta chave, ou None se ainda não existe."""
    if not chave:
        return None
    guardada = IdempotencyKey.objects.filter(key=chave).first()
    return guardada.response if guardada else None


def guardar_resposta(chave, resposta):
    """Guarda a resposta (só se correu bem) para repetir o mesmo resultado num reenvio."""
    if chave and 200 <= resposta.status_code < 300:
        IdempotencyKey.objects.create(key=chave, response=resposta.data)


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

    def terminar(self, request, pk=None):
        chave = request.headers.get("Idempotency-Key")
        guardada = resposta_guardada(chave)
        if guardada is not None:
            return Response(guardada)

        # Executar e guardar a resposta na MESMA transação.
        with transaction.atomic():
            internamento = services.dar_alta(self.get_object().pk)
            resposta = Response({"status": "Internamento terminado com sucesso",
                                 "alta": internamento.alta.isoformat()},
                                status=status.HTTP_200_OK)
            guardar_resposta(chave, resposta)
        return resposta

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

    def reconhecer(self, request, pk=None):
        chave = request.headers.get("Idempotency-Key")
        guardada = resposta_guardada(chave)
        if guardada is not None:
            return Response(guardada)

        self.get_object()                    # 404 se o alarme não for visível a este utilizador
        with transaction.atomic():
            try:
                alarme, _ = services.reconhecer_alarme(
                    pk, request.user, ip=services.ip_do_pedido(request))
            except services.AlarmeJaReconhecido as e:
                return Response(
                    {"detail": f"alarme já reconhecido por {getattr(e.por, 'username', '?')}"},
                    status=status.HTTP_409_CONFLICT)
            # PermissionDenied (médico, outra enfermaria) propaga-se e o DRF converte em 403.
            resposta = Response(AlarmeSerializer(alarme).data, status=status.HTTP_200_OK)
            guardar_resposta(chave, resposta)
        return resposta
