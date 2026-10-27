"""Povoamento com dados sintéticos.

Sem volume de dados, o exercício do N+1 não impressiona. Por omissão:
20 doentes, 20 internamentos ativos, 60 dispositivos, 50 000 leituras.

  python manage.py seed_sivit
  python manage.py seed_sivit --leituras 200000 --limpar
"""
import random
import os

from django.contrib.auth import get_user_model
from vigilancia.models import Alarme, Perfil
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from vigilancia.models import Dispositivo, Doente, Internamento, Leitura

TIPOS = ["ECG", "SpO2", "PANI", "TEMP"]
PARAMETROS = {"ECG": ("FC", "bpm", 60, 100), "SpO2": ("SPO2", "%", 92, 100),
              "PANI": ("PAS", "mmHg", 100, 140), "TEMP": ("TEMP", "C", 36.0, 37.5)}

# Lista de nomes reais para substituir os "Doentes Sintéticos" genéricos,
# dando um aspeto muito mais profissional e imersivo ao painel.
NOMES_REAIS = [
    "Inês Freitas", "Afonso Lopes", "Beatriz Mendes", 
    "Margarida Silva", "Rita Oliveira", "Gonçalo Ribeiro", 
    "Bernardo Santos", "Matilde Costa", "Inês Almeida", 
    "Tiago Ferreira", "Diogo Carvalho", "Beatriz Martins",
    "Tomás Pereira", "Carolina Rodrigues", "Francisco Sousa",
    "Mafalda Fernandes", "Rodrigo Pinto", "Clara Mendes",
    "Afonso Ribeiro", "Beatriz Esteves", "Duarte Simões"
]


class Command(BaseCommand):
    help = "Cria dados sintéticos do SIVIT com nomes reais."

    def add_arguments(self, parser):
        parser.add_argument("--doentes", type=int, default=20)
        parser.add_argument("--dispositivos-por-internamento", type=int, default=3)
        parser.add_argument("--leituras", type=int, default=50_000)
        parser.add_argument("--limpar", action="store_true")

    def handle(self, *args, **o):
        if o["limpar"]:
            Leitura.objects.all().delete()
            Dispositivo.objects.all().delete()
            Internamento.objects.all().delete()
            Doente.objects.all().delete()

        agora = timezone.now()
        
        # Atribui um nome real de forma consistente com base no índice 'n' do doente
        doentes = []
        for n in range(1, o["doentes"] + 1):
            nome_escolhido = NOMES_REAIS[(n - 1) % len(NOMES_REAIS)]
            doentes.append(Doente(
                codigo=f"D{n:04d}", 
                nome=nome_escolhido,
                data_nascimento="1960-01-01"
            ))

        Doente.objects.bulk_create(doentes, ignore_conflicts=True)
        # using("default"): um comando de povoamento escreve na primária e tem
        # de reler da primária. Ler de uma réplica logo a seguir a escrever é
        # a violação de read-your-writes que TP7 estuda, e aqui daria
        # simplesmente uma lista vazia.
        doentes = list(Doente.objects.using("default").all())

        # Repetível: só abre internamento a quem não tem um ativo. Sem isto,
        # correr o seed duas vezes duplica internamentos e dispositivos, e os
        # números das tabelas das aulas seguintes deixam de bater certo.
        ja_internados = set(Internamento.objects.using("default")
                            .filter(alta__isnull=True)
                            .values_list("doente_id", flat=True))
        internamentos = [Internamento(doente=d, enfermaria=f"ENF{(i % 4) + 1}",
                                      cama=f"C{i:02d}",
                                      admissao=agora - timedelta(days=random.randint(1, 10)))
                         for i, d in enumerate(doentes) if d.pk not in ja_internados]
        Internamento.objects.bulk_create(internamentos)
        internamentos = list(Internamento.objects.using("default")
                             .filter(alta__isnull=True))

        # O número de série é derivado do CÓDIGO DO DOENTE e não da chave
        # primária do internamento: assim SN-0001-0 existe sempre, mesmo
        # depois de correr o seed várias vezes, e os exemplos das aulas
        # seguintes continuam a funcionar.
        dispositivos = []
        for i in internamentos:
            n = int(i.doente.codigo.lstrip("D"))
            for k in range(o["dispositivos_por_internamento"]):
                dispositivos.append(Dispositivo(
                    numero_serie=f"SN-{n:04d}-{k}", tipo=TIPOS[k % len(TIPOS)],
                    internamento=i))
        Dispositivo.objects.bulk_create(dispositivos, ignore_conflicts=True)
        dispositivos = list(Dispositivo.objects.using("default").all())

        total, lote, por_disp = o["leituras"], [], max(1, o["leituras"] // len(dispositivos))
        for d in dispositivos:
            p, unidade, lo, hi = PARAMETROS[d.tipo]
            base = agora - timedelta(seconds=por_disp)
            for s in range(por_disp):
                lote.append(Leitura(dispositivo=d, instante=base + timedelta(seconds=s),
                                    parametro=p, valor=round(random.uniform(lo, hi), 1),
                                    unidade=unidade))
                if len(lote) >= 5000:
                    Leitura.objects.bulk_create(lote, ignore_conflicts=True)
                    lote = []
        if lote:
            Leitura.objects.bulk_create(lote, ignore_conflicts=True)

        self._criar_utilizadores()
        self._criar_alarmes_demo()

        self.stdout.write(self.style.SUCCESS(
            f"doentes={Doente.objects.using('default').count()} "
            f"internamentos={Internamento.objects.using('default').count()} "
            f"dispositivos={Dispositivo.objects.using('default').count()} "
            f"leituras={Leitura.objects.using('default').count()}"))
