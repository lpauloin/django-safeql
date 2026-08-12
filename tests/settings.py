import os

SECRET_KEY = "test"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DJANGO_SAFEQL_TEST_DB", "django_safeql"),
        "USER": os.environ.get("DJANGO_SAFEQL_TEST_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_SAFEQL_TEST_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_SAFEQL_TEST_DB_HOST", ""),
        "PORT": os.environ.get("DJANGO_SAFEQL_TEST_DB_PORT", ""),
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.testapp",
]

# The test app ships no migrations on purpose — tables are created via
# Django's syncdb fallback so contributors don't need to regenerate
# migrations every time the sample schema changes.
MIGRATION_MODULES = {"testapp": None}

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
