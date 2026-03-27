import time

from django.core.management import BaseCommand
from django.db import connections, OperationalError


class Command(BaseCommand):
    """Django command to wait until the database is available."""

    def handle(self, *args, **kwargs) -> None:
        self.stdout.write("Waiting for database...")
        db_connection = None
        while not db_connection:
            try:
                db_connection = connections["default"]
            except OperationalError:
                self.stdout.write(self.style.ERROR("Database unavailable."))
                time.sleep(1)
        self.stdout.write(self.style.SUCCESS("Database available."))
