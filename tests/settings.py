import os

SECRET_KEY = "test"

# DJANGO_SAFEQL_TEST_BACKEND selects which database the suite runs against so the same
# tests can verify each supported target. Postgres is the default; sqlite needs no
# service; mysql is driven from the same env vars as postgres.
TEST_BACKEND = os.environ.get("DJANGO_SAFEQL_TEST_BACKEND", "postgresql")

if TEST_BACKEND == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
else:
    if TEST_BACKEND == "mysql":
        try:
            import MySQLdb  # noqa: F401
        except ImportError:
            # Fall back to the pure-Python driver when mysqlclient is not installed.
            import pymysql

            pymysql.install_as_MySQLdb()
    ENGINES = {
        "postgresql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
    }
    DATABASES = {
        "default": {
            "ENGINE": ENGINES[TEST_BACKEND],
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
