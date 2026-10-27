from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", RedirectView.as_view(url="/painel/", permanent=False)),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),   # só aceita POST (Django 5)
    path("painel/", views.painel, name="painel"),
    path("doentes/<int:internamento_id>/", views.doente_detalhe, name="doente"),
    path("alarmes/<int:alarme_id>/reconhecer/", views.reconhecer_alarme,
         name="reconhecer_alarme"),
    path("saude/", views.saude, name="saude"),     # pública: é o healthcheck
]
