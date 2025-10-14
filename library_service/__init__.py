try:
    from library_service.celery import app as celery_app

    __all__ = ("celery_app",)
except ImportError:
    # Celery not installed - skip initialization
    # This allows tests to run without Celery
    celery_app = None
    __all__ = ()
