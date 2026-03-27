"""
It's a batch utility to create fine payments for books that were returned late but don't have fine payments yet.
When You'd Need This
✅ Useful for:
1.Migrating from old system - If you had overdue returns BEFORE implementing fines
2.Fixing missed fines - If your webhook or return process failed to create some fines
3.Data cleanup - Finding inconsistencies in your payment records
4.One-time backfill - After deploying the fixed code
"""

from django.core.management.base import BaseCommand
from django.db.models import F
from borrowings.models import Borrowing
from payments.services import create_fine_payment_for_borrowing


class Command(BaseCommand):
    help = "Create fine payments for all overdue borrowings that don't have them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually creating payments",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find borrowings that were returned LATE and don't have fine payments
        overdue_borrowings = (
            Borrowing.objects.filter(
                actual_return_date__isnull=False,  # Returned
                actual_return_date__gt=F("expected_return_date"),  # Returned LATE
            )
            .exclude(payments__type="fine")  # No fine payment exists
            .select_related("book", "user")
        )

        count = overdue_borrowings.count()
        self.stdout.write(f"\nFound {count} late returns without fine payments\n")

        if count == 0:
            self.stdout.write(self.style.SUCCESS("✅ No missing fines found!"))
            return

        created_count = 0
        skipped_count = 0
        errors = []

        for borrowing in overdue_borrowings:
            try:
                # Use the property, not non-existent method
                fine_amount = borrowing.fine_fee
                days_late = borrowing.days_overdue

                if fine_amount <= 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  Skipping borrowing {borrowing.id}: "
                            f"Fine amount is ${fine_amount} (should be > 0)"
                        )
                    )
                    skipped_count += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"Would create fine for borrowing {borrowing.id}:\n"
                        f"  Book: {borrowing.book.title}\n"
                        f"  User: {borrowing.user.email}\n"
                        f"  Days late: {days_late}\n"
                        f"  Fine amount: ${fine_amount}\n"
                    )
                else:
                    # Create fine payment (without Stripe session for batch operation)
                    fine_payment = create_fine_payment_for_borrowing(
                        borrowing, request=None  # No session for batch
                    )
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ Created fine payment {fine_payment.id} "
                            f"for borrowing {borrowing.id}: ${fine_payment.money_to_pay}"
                        )
                    )
            except Exception as e:
                error_msg = (
                    f"❌ Failed to create fine for borrowing {borrowing.id}: {str(e)}"
                )
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(error_msg))

        # Summary
        self.stdout.write("\n" + "=" * 50)
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: Would create {count} fine payments")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ Successfully created {created_count} fine payments"
                )
            )
            if skipped_count > 0:
                self.stdout.write(
                    self.style.WARNING(f"⚠️  Skipped {skipped_count} (invalid amounts)")
                )

        if errors:
            self.stdout.write(self.style.ERROR(f"❌ Encountered {len(errors)} errors"))

        if not dry_run and created_count > 0:
            self.stdout.write(
                "\n💡 Note: Fine payments created without Stripe sessions.\n"
                "   Users need to visit their payments page to pay fines.\n"
            )
