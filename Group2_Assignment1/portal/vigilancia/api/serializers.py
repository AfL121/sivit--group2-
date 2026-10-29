from rest_framework import serializers
from vigilancia.models import Alarme, Doente, Internamento, Dispositivo, Leitura

# Os limites vivem num só sítio (services.py): o portal e, mais tarde, os
# consumidores usam a mesma regra.
from vigilancia.services import LIMITES_PLAUSIVEIS

class DoenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Doente
        fields = ["codigo", "nome", "data_nascimento"]

class InternamentoSerializer(serializers.ModelSerializer):
    doente = DoenteSerializer(read_only=True)

    class Meta:
        model = Internamento
        fields = ["id", "doente", "enfermaria", "cama", "admissao", "alta", "versao"]

class DispositivoSerializer(serializers.ModelSerializer):
    admission = serializers.SerializerMethodField()

    class Meta:
        model = Dispositivo
        fields = ["numero_serie", "tipo", "admission"]

   
    def get_admission(self, obj):
        # Só conta um internamento ATIVO. None = dispositivo sem internamento.
        i = obj.internamento
        return i.pk if i is not None and i.alta is None else None

class ReadingSerializer(serializers.ModelSerializer):
    # O gateway conhece o número de série, não o nosso id primário. Nunca expor IDs internos (TP3 - Ex 1).
    dispositivo = serializers.SlugRelatedField(
        slug_field="numero_serie", queryset=Dispositivo.objects.all()
    )

    class Meta:
        model = Leitura
        fields = ["dispositivo", "instante", "parametro", "valor", "unidade"]

    def validate(self, data):
        # Os campos do serializer são "parametro" e "valor" (não "parameter"/"value").
        lo, hi = LIMITES_PLAUSIVEIS.get(data["parametro"], (float("-inf"), float("inf")))
        if not lo <= data["valor"] <= hi:
            raise serializers.ValidationError("valor fora do intervalo plausível")
        return data

class AlarmeSerializer(serializers.ModelSerializer):
    dispositivo = serializers.SlugRelatedField(slug_field="numero_serie", read_only=True)
    enfermaria = serializers.CharField(source="internamento.enfermaria",
                                       read_only=True, allow_null=True)
    cama = serializers.CharField(source="internamento.cama",
                                 read_only=True, allow_null=True)
    reconhecido_por = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = Alarme
        fields = ["id", "dispositivo", "enfermaria", "cama", "regra", "parametro",
                  "valor", "mensagem", "estado", "criado_em",
                  "reconhecido_por", "reconhecido_em"]
