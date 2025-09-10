from django.urls import path, include
from rest_framework import routers

from payments.views import PaymentViewSet

app_name = "payments"

router = routers.DefaultRouter()
router.register("", PaymentViewSet, basename="payments")

urlpatterns = [
    path("", include(router.urls)),
]
