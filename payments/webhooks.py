import json
import stripe
import logging
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.views import View
from django.utils.decorators import method_decorator

from payments.models import Payment

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    """
    Class-based view for handling Stripe webhooks
    """

    def post(self, request):
        """Handle Stripe webhook POST requests"""
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

        # Debug logging (remove in production)
        logger.info(f"Webhook received - Body length: {len(payload)}")
        logger.info(f"Signature present: {bool(sig_header)}")
        logger.info(f"Webhook secret configured: {bool(endpoint_secret)}")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
            logger.info(f"Event verified: {event['type']}")

        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            return HttpResponse(status=400)

        # Handle the checkout.session.completed event
        if event["type"] == "checkout.session.completed":
            return self.handle_checkout_completed(event)
        else:
            logger.info(f"Unhandled event type: {event['type']}")

        return HttpResponse(status=200)

    def handle_checkout_completed(self, event):
        """Handle successful checkout completion"""
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

                # Optional: Add notification logic here
                # self.notify_payment_success(payment)

            else:
                logger.warning(
                    f"Payment not updated - Current: {payment.status}, Stripe: {payment_status}"
                )

        except Payment.DoesNotExist:
            logger.error(f"Payment not found for session {session_id}")

        return HttpResponse(status=200)

    def notify_payment_success(self, payment):
        """Optional: Send notifications when payment is successful"""
        # You can add email/telegram notifications here
        pass


@csrf_exempt
@require_POST
def stripe_webhook_enhanced(request):
    """
    Enhanced webhook function with detailed logging for debugging
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    # Debug logging (remove prints in production)
    print(f"=== WEBHOOK RECEIVED ===")
    print(f"Body length: {len(payload)}")
    print(f"Signature header: {sig_header[:20] if sig_header else 'None'}...")
    print(f"Webhook secret configured: {bool(endpoint_secret)}")

    # Create a simple log file (remove in production)
    try:
        with open("webhook_debug.log", "a") as f:
            f.write(f"Webhook called at {timezone.now()}\n")
    except Exception:
        pass  # Don't fail if can't write to log

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        print(f"✅ Event verified: {event['type']}")

    except ValueError as e:
        print(f"❌ Invalid payload: {e}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ Invalid signature: {e}")
        return HttpResponse(status=400)

    # Handle the checkout.session.completed event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        session_id = session["id"]
        payment_status = session.get("payment_status")

        print(f"Processing session {session_id} with status {payment_status}")

        try:
            payment = Payment.objects.select_for_update().get(session_id=session_id)
            print(f"Found payment {payment.id} with current status: {payment.status}")

            if payment.status == "pending" and payment_status == "paid":
                payment.status = "paid"
                payment.save()
                print(f"✅ Payment {payment.id} marked as paid!")
            else:
                print(
                    f"⚠️ Payment not updated - Current: {payment.status}, Stripe: {payment_status}"
                )

        except Payment.DoesNotExist:
            print(f"❌ Payment not found for session {session_id}")
    else:
        print(f"ℹ️ Unhandled event type: {event['type']}")

    return HttpResponse(status=200)


# Webhook event handlers
def handle_payment_intent_succeeded(event):
    """Handle successful payment intent"""
    payment_intent = event["data"]["object"]
    # Add your logic here
    pass


def handle_payment_method_attached(event):
    """Handle payment method attachment"""
    payment_method = event["data"]["object"]
    # Add your logic here
    pass


# Event handler mapping
WEBHOOK_HANDLERS = {
    "checkout.session.completed": lambda event: None,  # Handled in main function
    "payment_intent.succeeded": handle_payment_intent_succeeded,
    "payment_method.attached": handle_payment_method_attached,
}


@csrf_exempt
@require_POST
def stripe_webhook_router(request):
    """
    Advanced webhook router that can handle multiple event types
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return HttpResponse(status=400)

    event_type = event["type"]
    handler = WEBHOOK_HANDLERS.get(event_type)

    if handler:
        try:
            handler(event)
            logger.info(f"Successfully handled event: {event_type}")
        except Exception as e:
            logger.error(f"Error handling event {event_type}: {e}")
            return HttpResponse(status=500)
    else:
        logger.info(f"Unhandled event type: {event_type}")

    return HttpResponse(status=200)
