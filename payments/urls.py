from django.urls import path, include
from rest_framework import routers

from payments.views import (
    PaymentViewSet,
    payment_success,
    payment_cancel,
)

from payments.webhooks import StripeWebhookView

app_name = "payments"

router = routers.DefaultRouter()
router.register("", PaymentViewSet, basename="payments")

urlpatterns = [
    # Stripe webhook must come first (or outside router) to avoid 401
    path("webhook/", StripeWebhookView.as_view(), name="stripe_webhook"),
    # Payment CRUD endpoints (DRF)
    path("", include(router.urls)),
    # Payment completion endpoints
    path("success/", payment_success, name="payment_success"),
    path("cancel/", payment_cancel, name="payment_cancel"),
]
