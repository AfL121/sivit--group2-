from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from .views import DoenteViewSet, InternamentoViewSet, DispositivoViewSet, ReadingViewSet

router = DefaultRouter()
router.register(r"patients", DoenteViewSet, basename="patient")
router.register(r"admissions", InternamentoViewSet, basename="admission")
router.register(r"devices", DispositivoViewSet, basename="device")
router.register(r"readings", ReadingViewSet, basename="reading")

urlpatterns = [
    path("v1/", include(router.urls)),
    # Documentação OpenAPI / Swagger UI exigida na TP3
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]