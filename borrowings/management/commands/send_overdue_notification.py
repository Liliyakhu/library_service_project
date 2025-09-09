from django.core.management.base import BaseCommand
from notifications.tasks import send_overdue_notification


class Command(BaseCommand):
    help = "Test overdue notification for a specific borrowing ID"

    def add_arguments(self, parser):
        parser.add_argument(
            "borrowing_id", type=int, help="ID of the borrowing to test"
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run the task asynchronously using Celery",
        )

    def handle(self, *args, **options):
        borrowing_id = options["borrowing_id"]

        self.stdout.write(f"Testing notification for borrowing ID: {borrowing_id}")

        if options["async"]:
            # Run asynchronously
            task = send_overdue_notification.delay(borrowing_id)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Task queued successfully! Task ID: {task.id}")
            )
        else:
            # Run synchronously
            result = send_overdue_notification(borrowing_id)

            if result["status"] == "success":
                self.stdout.write(
                    self.style.SUCCESS("✅ Notification sent successfully!")
                )
            elif result["status"] == "skipped":
                self.stdout.write(self.style.WARNING(f'⚠️  Skipped: {result["reason"]}'))
            elif result["status"] == "failed":
                self.stdout.write(self.style.ERROR(f'❌ Failed: {result["message"]}'))
            else:
                self.stdout.write(self.style.ERROR(f'❌ Error: {result["message"]}'))
