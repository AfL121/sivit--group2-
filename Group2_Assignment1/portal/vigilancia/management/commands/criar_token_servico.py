import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Cria o utilizador de serviço 'ingestao' com o token vindo do ambiente."

    def handle(self, *args, **opcoes):
        chave = os.environ.get("PORTAL_SERVICE_TOKEN")
        if not chave:
            self.stdout.write("PORTAL_SERVICE_TOKEN não definido: nada a fazer")
            return
        user, criado = get_user_model().objects.get_or_create(username="ingestao")
        if criado:
            user.set_unusable_password()
            user.save()
        Token.objects.filter(user=user).exclude(key=chave).delete()
        Token.objects.get_or_create(user=user, defaults={"key": chave})
        self.stdout.write("token de serviço pronto")
