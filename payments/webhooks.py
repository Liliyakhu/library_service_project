import stripe
import logging

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views import View
from django.utils.decorators import method_decorator

from payments.models import Payment
from notifications.telegram import send_telegram_message
from notifications.formatters import format_payment_success_notification

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    """
    Class-based view for handling Stripe webhooks.

    IMPROVED: Better logging, uses centralized formatter.
    """

    def post(self, request):
        """Handle Stripe webhook POST requests."""
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

        logger.info(f"Webhook received - Body length: {len(payload)}")
        logger.info(f"Signature present: {bool(sig_header)}")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
            logger.info(f"Event verified: {event['type']}")
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.error(f"Webhook verification failed: {e}")
            return HttpResponse(status=400)

        if event["type"] == "checkout.session.completed":
            return self.handle_checkout_completed(event)

        logger.info(f"Unhandled event type: {event['type']}")
        return HttpResponse(status=200)

    def handle_checkout_completed(self, event):
        """
        Handle successful checkout completion.

        IMPROVED: Uses centralized notification formatter.
        """
        session = event["data"]["object"]
        session_id = session["id"]
        payment_status = session.get("payment_status")

        logger.info(f"Processing session {session_id} with status {payment_status}")

        try:
            payment = Payment.objects.select_for_update().get(session_id=session_id)
            logger.info(
                f"Found payment {payment.id} with current status: {payment.status}"
            )

            if payment.status == "pending" and payment_status == "paid":
                payment.status = "paid"
                payment.save()
                logger.info(f"Payment {payment.id} marked as paid!")

                # Send notification using centralized formatter
                try:
                    message = format_payment_success_notification(payment)
                    send_telegram_message(message)
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")

            else:
                logger.warning(
                    f"Payment not updated - Current: {payment.status}, "
                    f"Stripe: {payment_status}"
                )

        except Payment.DoesNotExist:
            logger.error(f"Payment not found for session {session_id}")

        return HttpResponse(status=200)
