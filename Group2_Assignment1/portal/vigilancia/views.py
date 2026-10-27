"""Painel de internamentos ativos, nas quatro versões do exercício 4.

A versão é escolhida por ?modo=..., para que a mesma página possa ser medida
lado a lado:  /painel/?modo=ingenuo  ...  /painel/?modo=subquery
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Prefetch, Subquery
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .models import Alarme, Dispositivo, Internamento, Leitura, Perfil


def _linhas_ingenuo():
    linhas = []
    for i in Internamento.objects.filter(alta__isnull=True):       # 1 consulta
        for d in i.dispositivos.all():                             # N consultas
            ultima = d.leituras.order_by("-instante").first()      # N×M consultas
            resumo = (f"{ultima.parametro} {ultima.valor} em {ultima.instante:%H:%M:%S}"
                      if ultima else "sem leituras")
            linhas.append((i.doente.nome, d.tipo, resumo))         # + N consultas
    return linhas


def _linhas_select_related():
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente"))                  # JOIN, não consulta por linha
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            ultima = d.leituras.order_by("-instante").first()
            resumo = (f"{ultima.parametro} {ultima.valor} em {ultima.instante:%H:%M:%S}"
                      if ultima else "sem leituras")
            linhas.append((i.doente.nome, d.tipo, resumo))
    return linhas


def _linhas_prefetch():
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente")
                .prefetch_related("dispositivos"))           # 1 consulta extra, não N
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            ultima = d.leituras.order_by("-instante").first()
            resumo = (f"{ultima.parametro} {ultima.valor} em {ultima.instante:%H:%M:%S}"
                      if ultima else "sem leituras")
            linhas.append((i.doente.nome, d.tipo, resumo))
    return linhas


def _linhas_subquery():
    """Uma consulta agregada em vez de N×M: a última leitura vem anotada."""
    ultima = (Leitura.objects
              .filter(dispositivo=OuterRef("pk"))
              .order_by("-instante"))
    com_ultima = Dispositivo.objects.annotate(
        ultimo_valor=Subquery(ultima.values("valor")[:1]),
        ultimo_instante=Subquery(ultima.values("instante")[:1]),
        ultimo_parametro=Subquery(ultima.values("parametro")[:1]),
    )
    consulta = (Internamento.objects
                .filter(alta__isnull=True)
                .select_related("doente")
                .prefetch_related(Prefetch("dispositivos", queryset=com_ultima)))
    linhas = []
    for i in consulta:
        for d in i.dispositivos.all():
            resumo = (f"{d.ultimo_parametro} {d.ultimo_valor} em {d.ultimo_instante:%H:%M:%S}"
                      if d.ultimo_instante else "sem leituras")
            linhas.append((i.doente.nome, d.tipo, resumo))
    return linhas


MODOS = {
    "ingenuo": _linhas_ingenuo,
    "select": _linhas_select_related,
    "prefetch": _linhas_prefetch,
    "subquery": _linhas_subquery,
}


@login_required
def painel(request):
    internamentos = list(services.painel_dados(request.user))
    services.auditar(request.user, "VER_PAINEL", request.path,
                     services.ip_do_pedido(request),
                     [i.doente.codigo for i in internamentos])
    return render(request, "painel.html", {
        "internamentos": internamentos,
        "pode_reconhecer": services.papel(request.user) == Perfil.ENFERMEIRO,
    })


@login_required
def doente_detalhe(request, internamento_id):
    internamento = get_object_or_404(
        Internamento.objects.select_related("doente"), pk=internamento_id)
    if not services.pode_ver_enfermaria(request.user, internamento.enfermaria):
        raise PermissionDenied
    services.auditar(request.user, "VER_DOENTE", request.path,
                     services.ip_do_pedido(request), [internamento.doente.codigo])
    leituras = (Leitura.objects.filter(dispositivo__internamento=internamento)
                .select_related("dispositivo").order_by("-instante")[:30])
    alarmes = (internamento.alarmes.select_related("reconhecido_por", "dispositivo")
               .order_by("-criado_em")[:20])
    return render(request, "doente.html", {
        "internamento": internamento, "leituras": leituras, "alarmes": alarmes})


@login_required
@require_POST
def reconhecer_alarme(request, alarme_id):
    try:
        alarme, novo = services.reconhecer_alarme(
            alarme_id, request.user, ip=services.ip_do_pedido(request))
    except Alarme.DoesNotExist:
        raise Http404
    except services.AlarmeJaReconhecido as e:
        quem = getattr(e.por, "username", "outro profissional")
        messages.error(request, f"Este alarme já foi reconhecido por {quem}.")
    else:
        messages.success(request, "Alarme reconhecido." if novo
                         else "Já tinha reconhecido este alarme.")
    return redirect("painel")


def saude(request):
    """Prontidão: só responde 200 se a base de dados responder."""
    from django.db import connection
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({"estado": "pronto"})
    except Exception as e:                        # noqa: BLE001
        return JsonResponse({"estado": "indisponivel", "erro": str(e)}, status=503)
