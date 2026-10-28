from django.db import models
from django.conf import settings
from django.utils import timezone


class Doente(models.Model):
    codigo = models.CharField(max_length=32, unique=True)
    nome = models.CharField(max_length=120)          # pseudonimizado, sintético
    data_nascimento = models.DateField()

    def __str__(self):
        return f"{self.codigo} ({self.nome})"


class Internamento(models.Model):
    doente = models.ForeignKey(Doente, on_delete=models.PROTECT,
                               related_name="internamentos")
    enfermaria = models.CharField(max_length=32)
    cama = models.CharField(max_length=16)
    admissao = models.DateTimeField()
    alta = models.DateTimeField(null=True, blank=True)
    # TP3-E2: concorrência otimista com If-Match/ETag.
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        indexes = [models.Index(fields=["alta"])]


class Dispositivo(models.Model):
    numero_serie = models.CharField(max_length=64, unique=True)
    tipo = models.CharField(max_length=16)           # ECG, SpO2, PANI, TEMP
    internamento = models.ForeignKey(Internamento, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name="dispositivos")

    def __str__(self):
        return self.numero_serie


class Leitura(models.Model):
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.CASCADE,
                                    related_name="leituras")
    instante = models.DateTimeField(db_index=True)
    parametro = models.CharField(max_length=16)      # FC, SPO2, TEMP, PAS, ...
    valor = models.FloatField()
    unidade = models.CharField(max_length=8)

    class Meta:
        # Idempotência na ingestão. Não é decoração: é o mecanismo que torna
        # inofensivo o reenvio por timeout do gateway. Ver TP3, TP5 e T7.
        constraints = [
            models.UniqueConstraint(fields=["dispositivo", "instante", "parametro"],
                                    name="uniq_leitura"),
        ]
        indexes = [models.Index(fields=["dispositivo", "-instante"])]

class IdempotencyKey(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    response = models.JSONField()
    created = models.DateTimeField(auto_now_add=True)


class Perfil(models.Model):
    ENFERMEIRO = "ENFERMEIRO"
    MEDICO = "MEDICO"
    PAPEIS = [(ENFERMEIRO, "Enfermeiro"), (MEDICO, "Médico")]

    utilizador = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                      related_name="perfil")
    papel = models.CharField(max_length=16, choices=PAPEIS)
    # Só faz sentido para enfermeiros; o médico vê todas.
    enfermaria = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return f"{self.utilizador} ({self.papel} {self.enfermaria})".strip()


class Alarme(models.Model):
    ATIVO, RECONHECIDO, RESOLVIDO = "ATIVO", "RECONHECIDO", "RESOLVIDO"
    ESTADOS = [(ATIVO, "Ativo"), (RECONHECIDO, "Reconhecido"), (RESOLVIDO, "Resolvido")]

    # Chave de idempotência do detetor (ponto 3): regra|dispositivo|início do episódio.
    # Se o worker for reentregue, o UNIQUE impede um segundo alarme igual.
    chave = models.CharField(max_length=128, unique=True)
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.CASCADE, related_name="alarmes")
    # Internamento "congelado" no momento do alarme: o dispositivo pode mudar de cama depois.
    internamento = models.ForeignKey(Internamento, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="alarmes")
    regra = models.CharField(max_length=32)
    parametro = models.CharField(max_length=16)
    valor = models.FloatField()
    mensagem = models.CharField(max_length=200)
    estado = models.CharField(max_length=16, choices=ESTADOS, default=ATIVO)
    criado_em = models.DateTimeField(default=timezone.now)
    reconhecido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name="alarmes_reconhecidos")
    reconhecido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["estado", "-criado_em"])]


class EstadoAlarme(models.Model):
    dispositivo = models.ForeignKey(
        Dispositivo,
        on_delete=models.CASCADE,
        related_name="estados_alarme"
    )

    regra = models.CharField(max_length=32)

    inicio_episodio = models.DateTimeField(null=True, blank=True)

    ultimo_instante = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dispositivo", "regra"],
                name="uniq_estado_alarme"
            )
        ]


class Auditoria(models.Model):
    utilizador = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    acao = models.CharField(max_length=32)
    # Código copiado, sem FK: o registo de auditoria sobrevive a qualquer apagamento.
    doente_codigo = models.CharField(max_length=32, blank=True)
    detalhe = models.CharField(max_length=200, blank=True)
    caminho = models.CharField(max_length=200, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    instante = models.DateTimeField(default=timezone.now, db_index=True)
