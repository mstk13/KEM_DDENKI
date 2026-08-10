from django.apps import AppConfig


class WorkersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.workers"
    verbose_name = "人材管理"

    def ready(self):
        import apps.workers.models  # noqa: F401 — registers signals
