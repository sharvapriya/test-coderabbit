from django.apps import AppConfig


class SellersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sellers"

    def ready(self):
        # Ensure payout signal handlers are registered at startup.
        from . import signals  # noqa: F401

