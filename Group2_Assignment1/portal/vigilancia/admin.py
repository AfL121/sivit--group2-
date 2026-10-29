from django.contrib import admin

from .models import (Alarme, Auditoria, Dispositivo, Doente, Internamento,
                     Leitura, Perfil)

admin.site.register([Doente, Internamento, Dispositivo, Leitura, Perfil, Alarme])


class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("instante", "utilizador", "acao", "doente_codigo", "ip")
    list_filter = ("acao",)

    # Registo de auditoria: só se lê.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(Auditoria, AuditoriaAdmin)
