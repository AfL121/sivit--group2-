"""Camada de serviço: lógica de domínio sem HTTP.

As views (TP2), a API (TP3) e os consumidores de fila (TP5) chamam estas
funções, por isso a regra de negócio existe uma só vez e é testável sem
cliente HTTP.
"""
import ipaddress

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils import timezone

from .models import (Alarme, Auditoria, Dispositivo, Doente, Internamento,
                     Leitura, Perfil)

LIMITES_PLAUSIVEIS = {
    "FC": (20, 250), "SPO2": (50, 100), "TEMP": (30, 45),
    "PAS": (40, 260), "PAD": (20, 160), "FR": (4, 60),
}


class ValorImplausivel(ValueError):
    pass


class AlarmeJaReconhecido(Exception):
    def __init__(self, por):
        super().__init__("alarme já reconhecido")
        self.por = por


# ----------------------------------------------------------------- leituras / internamentos
def registar_leitura(numero_serie, instante, parametro, valor, unidade):
    """Devolve (leitura, criada). Reenviar a mesma leitura não duplica."""
    limites = LIMITES_PLAUSIVEIS.get(parametro)
    if limites and not limites[0] <= valor <= limites[1]:
        raise ValorImplausivel(
            f"valor {valor} fora do intervalo plausível para {parametro}")

    dispositivo = Dispositivo.objects.get(numero_serie=numero_serie)
    try:
        with transaction.atomic():
            leitura = Leitura.objects.create(
                dispositivo=dispositivo, instante=instante,
                parametro=parametro, valor=valor, unidade=unidade)
        return leitura, True
    except IntegrityError:
        return Leitura.objects.get(dispositivo=dispositivo, instante=instante,
                                   parametro=parametro), False


def abrir_internamento(codigo_doente, enfermaria, cama):
    doente = Doente.objects.get(codigo=codigo_doente)
    return Internamento.objects.create(
        doente=doente, enfermaria=enfermaria, cama=cama,
        admissao=timezone.now())


def dar_alta(internamento_id):
    with transaction.atomic():
        i = Internamento.objects.select_for_update().get(pk=internamento_id)
        if i.alta is None:
            i.alta = timezone.now()
            i.versao += 1
            i.save(update_fields=["alta", "versao"])
    return i


# ----------------------------------------------------------------- perfis e permissões
def _perfil(user):
    # RelatedObjectDoesNotExist herda de AttributeError, por isso o getattr com
    # valor por omissão cobre o utilizador sem perfil (ex.: conta de serviço).
    return getattr(user, "perfil", None)


def papel(user):
    p = _perfil(user)
    return p.papel if p else None


def pode_ver_enfermaria(user, enfermaria):
    if user.is_superuser:
        return True
    p = _perfil(user)
    return p is not None and (p.papel == Perfil.MEDICO or p.enfermaria == enfermaria)


def _restringir(user, qs, campo_enfermaria):
    """Médico e superuser veem tudo; enfermeiro só a sua enfermaria; sem perfil, nada."""
    if user.is_superuser:
        return qs
    p = _perfil(user)
    if p is None:
        return qs.none()
    if p.papel == Perfil.MEDICO:
        return qs
    return qs.filter(**{campo_enfermaria: p.enfermaria})


def internamentos_acessiveis(user):
    return _restringir(user, Internamento.objects.select_related("doente"), "enfermaria")


def internamentos_visiveis(user):
    return internamentos_acessiveis(user).filter(alta__isnull=True)


def doentes_visiveis(user):
    return _restringir(user, Doente.objects.all(), "internamentos__enfermaria").distinct()


def leituras_visiveis(user):
    return _restringir(user, Leitura.objects.select_related("dispositivo"),
                       "dispositivo__internamento__enfermaria")


def alarmes_visiveis(user):
    return _restringir(
        user,
        Alarme.objects.select_related("dispositivo", "internamento__doente",
                                      "reconhecido_por"),
        "internamento__enfermaria")


# ----------------------------------------------------------------- painel
def painel_dados(user):
    """Internamentos ativos visíveis, com dispositivos (+ última leitura) e alarmes.

    3 consultas no total, qualquer que seja o número de camas (sem N+1).
    Limitação conhecida: mostra a última leitura de cada dispositivo, não a
    última de cada parâmetro; o estado atual por parâmetro virá do consumidor
    do painel (ponto 3).
    """
    ultima = Leitura.objects.filter(dispositivo=OuterRef("pk")).order_by("-instante")
    dispositivos = Dispositivo.objects.annotate(
        ultimo_parametro=Subquery(ultima.values("parametro")[:1]),
        ultimo_valor=Subquery(ultima.values("valor")[:1]),
        ultimo_instante=Subquery(ultima.values("instante")[:1]),
    )
    alarmes = (Alarme.objects.exclude(estado=Alarme.RESOLVIDO)
               .select_related("reconhecido_por").order_by("-criado_em"))
    return (internamentos_visiveis(user)
            .prefetch_related(Prefetch("dispositivos", queryset=dispositivos),
                              Prefetch("alarmes", queryset=alarmes, to_attr="alarmes_ativos"))
            .order_by("enfermaria", "cama"))


# ----------------------------------------------------------------- reconhecimento exclusivo
def _carregar_alarme(alarme_id):
    return (Alarme.objects.select_related("dispositivo", "internamento__doente",
                                          "reconhecido_por").get(pk=alarme_id))


def reconhecer_alarme(alarme_id, user, ip=None):
    """Devolve (alarme, novo).

    Exclusão mútua: um único UPDATE condicional (... WHERE reconhecido_por IS NULL).
    Se dois enfermeiros clicam ao mesmo tempo, o PostgreSQL serializa as duas
    escritas na linha; a segunda reavalia o WHERE, já não encontra a linha
    livre e atualiza 0 linhas. Sem SELECT prévio, não há corrida
    verificar-depois-escrever.

    Idempotente para o mesmo utilizador: reenviar devolve o mesmo alarme (novo=False).
    """
    p = _perfil(user)
    if p is None or p.papel != Perfil.ENFERMEIRO:
        raise PermissionDenied("só enfermeiros reconhecem alarmes")
    alarme = _carregar_alarme(alarme_id)            # Alarme.DoesNotExist -> 404
    enfermaria = alarme.internamento.enfermaria if alarme.internamento else None
    if enfermaria != p.enfermaria:
        raise PermissionDenied("alarme de outra enfermaria")


    n = (Alarme.objects.filter(
            pk=alarme.pk,
            estado=Alarme.ATIVO,
            reconhecido_por__isnull=True
         )
         .update(
             estado=Alarme.RECONHECIDO,
             reconhecido_por=user,
             reconhecido_em=timezone.now()
         ))

    alarme = _carregar_alarme(alarme.pk)
    if n == 1:
        auditar(user, "RECONHECER_ALARME", ip=ip,
                doentes=[alarme.internamento.doente.codigo],
                detalhe=f"alarme {alarme.pk} ({alarme.regra})")
        return alarme, True

    if alarme.estado == Alarme.RESOLVIDO:
        raise PermissionDenied("não é possível reconhecer um alarme resolvido")

    if alarme.reconhecido_por_id == user.id:
        return alarme, False

    raise AlarmeJaReconhecido(alarme.reconhecido_por)



# ----------------------------------------------------------------- auditoria
def ip_do_pedido(request):
    bruto = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
             or request.META.get("REMOTE_ADDR", ""))
    try:
        return str(ipaddress.ip_address(bruto))
    except ValueError:
        return None          # cabeçalho forjado ou vazio: nunca deixar rebentar a escrita


def auditar(user, acao, caminho="", ip=None, doentes=(), detalhe=""):
    """Uma linha por doente acedido (ou uma linha sem doente)."""
    quem = user if getattr(user, "is_authenticated", False) else None
    Auditoria.objects.bulk_create([
        Auditoria(utilizador=quem, acao=acao, doente_codigo=codigo,
                  caminho=caminho[:200], ip=ip, detalhe=detalhe[:200])
        for codigo in (list(doentes) or [""])
    ])
