from rest_framework import serializers
from vigilancia.models import Doente, Internamento, Dispositivo, Leitura

# Limites plausíveis da TP3 (Exercício 1)
LIMITES = {"HR": (20, 250), "SPO2": (50, 100), "TEMP": (30, 45), "PAS": (40, 260), "PAD": (20, 160), "FR": (4, 60)}

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
    class Meta:
        model = Dispositivo
        fields = ["numero_serie", "tipo"]

class ReadingSerializer(serializers.ModelSerializer):
    # O gateway conhece o número de série, não o nosso id primário. Nunca expor IDs internos (TP3 - Ex 1).
    dispositivo = serializers.SlugRelatedField(
        slug_field="numero_serie", queryset=Dispositivo.objects.all()
    )

    class Meta:
        model = Leitura
        fields = ["dispositivo", "instante", "parametro", "valor", "unidade"]

    def validate(self, data):
        parametro = data.get("parameter") or data.get("parametro")
        valor = data.get("value") or data.get("valor")
        
        # Validação de limites plausíveis
        lo, hi = LIMITES.get(parametro, (float("-inf"), float("inf")))
        if valor is not None and not (lo <= valor <= hi):
            raise serializers.ValidationError("valor fora do intervalo plausível")
        return data