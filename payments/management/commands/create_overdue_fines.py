from django.core.management.base import BaseCommand
from django.utils import timezone
from borrowings.models import Borrowing
from payments.services import create_fine_payment_for_borrowing


class Command(BaseCommand):
    help = "Create fine payments for all overdue borrowings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually creating payments",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find all overdue borrowings without fine payments
        overdue_borrowings = Borrowing.objects.filter(
            actual_return_date__isnull=False,
        ).exclude(payments__type="fine")

        self.stdout.write(f"Found {overdue_borrowings.count()} overdue borrowings")

        created_count = 0
        errors = []

        for borrowing in overdue_borrowings:
            try:
                if dry_run:
                    fine_amount = borrowing.calculate_fine_amount()
                    self.stdout.write(
                        f"Would create fine for borrowing {borrowing.id}: ${fine_amount}"
                    )
                else:
                    fine_payment = create_fine_payment_for_borrowing(borrowing)
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Created fine payment {fine_payment.id} for borrowing {borrowing.id}: ${fine_payment.money_to_pay}"
                        )
                    )
            except Exception as e:
                error_msg = (
                    f"Failed to create fine for borrowing {borrowing.id}: {str(e)}"
                )
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(error_msg))

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully created {created_count} fine payments"
                )
            )

        if errors:
            self.stdout.write(self.style.WARNING(f"Encountered {len(errors)} errors"))
