import json
from django.core.management.base import BaseCommand
from payments.models import Payment
from payments.webhooks import StripeWebhookView


class Command(BaseCommand):
    help = 'Test webhook processing with sample data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--payment-id',
            type=int,
            help='Payment ID to mark as paid via simulated webhook',
        )

    def handle(self, *args, **options):
        payment_id = options.get('payment_id')

        if payment_id:
            try:
                payment = Payment.objects.get(id=payment_id)

                if not payment.session_id:
                    self.stdout.write(
                        self.style.ERROR(f'Payment {payment_id} has no session_id')
                    )
                    return

                # Simulate webhook data
                mock_event = {
                    "id": "evt_test_webhook",
                    "object": "event",
                    "type": "checkout.session.completed",
                    "data": {
                        "object": {
                            "id": payment.session_id,
                            "object": "checkout.session",
                            "payment_status": "paid",
                        }
                    },
                }

                webhook_view = StripeWebhookView()
                webhook_view.handle_checkout_completed(mock_event)

                self.stdout.write(
                    self.style.SUCCESS(f'Successfully processed webhook for payment {payment_id}')
                )

            except Payment.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Payment {payment_id} not found')
                )
        else:
            self.stdout.write(
                self.style.WARNING('Use --payment-id to test specific payment')
            )