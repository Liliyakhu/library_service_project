import importlib
from django.urls import reverse


def test_secret_key_loaded_from_env(monkeypatch):
    """
    Ensure SECRET_KEY is correctly loaded from the environment.
    """
    monkeypatch.setenv("SECRET_KEY", "testkey123")

    import library_service.settings as project_settings

    importlib.reload(project_settings)

    assert project_settings.SECRET_KEY == "testkey123"


def test_books_url_resolves():
    url = reverse("books:books-list")
    assert url == "/api/books/"  # or whatever your URL should be


def test_project_urls_import():
    """
    Ensure main URLs file imports without errors.
    """
    import library_service.urls  # noqa: F401


def test_celery_app_loads():
    """
    Ensure Celery app initializes and has expected config.
    """
    from library_service.celery import app

    assert app.main == "library_service"
    assert "json" in app.conf.accept_content
