from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

SECRET_KEY = "loadpath-demo-not-for-production"
DEBUG = True
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "billing",
    "accounts",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
ROOT_URLCONF = "config.urls"
CELERY_BEAT_SCHEDULE = {
    "credit-stale-invoices": {
        "task": "billing.tasks.apply_credit",
        "schedule": 3600,
    }
}
