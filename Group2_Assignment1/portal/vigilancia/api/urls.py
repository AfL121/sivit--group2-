from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.routers import DefaultRouter

from .views import (AlarmeViewSet, DispositivoViewSet, DoenteViewSet,
                    InternamentoViewSet, ReadingViewSet)

router = DefaultRouter()
router.register(r"patients", DoenteViewSet, basename="patient")
router.register(r"admissions", InternamentoViewSet, basename="admission")
router.register(r"devices", DispositivoViewSet, basename="device")
router.register(r"readings", ReadingViewSet, basename="reading")
router.register(r"alarms", AlarmeViewSet, basename="alarm")

urlpatterns = [
    path("v1/auth/token/", obtain_auth_token),      # utilizador+password -> token
    path("v1/", include(router.urls)),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"),
         name="swagger-ui"),
]
