from django.core.management.base import BaseCommand
from notifications.tasks import check_overdue_borrowings


class Command(BaseCommand):
    help = "Check for overdue borrowings and send notifications (run immediately)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run the task asynchronously using Celery",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting overdue borrowings check..."))

        if options["async"]:
            # Run asynchronously
            task = check_overdue_borrowings.delay()
            self.stdout.write(
                self.style.SUCCESS(f"✅ Task queued successfully! Task ID: {task.id}")
            )
            self.stdout.write(
                'Use "celery -A library_service flower" to monitor the task.'
            )
        else:
            # Run synchronously for immediate feedback
            result = check_overdue_borrowings()

            if result["status"] == "success" and result["overdue_count"] == 0:
                self.stdout.write(self.style.SUCCESS("✅ No overdue borrowings found!"))
            elif result["status"] == "completed":
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Check completed! Found {result["overdue_count"]} overdue borrowings. '
                        f'Sent {result["successful_notifications"]} notifications.'
                    )
                )
                if result["failed_notifications"] > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f'⚠️  {result["failed_notifications"]} notifications failed to send.'
                        )
                    )
            else:
                self.stdout.write(self.style.ERROR("❌ Task completed with errors."))
