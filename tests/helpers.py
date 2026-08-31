import pytest
from django.db import connection

# For tests that assert a specific rejection message from a PostgreSQL-only feature.
# On other targets that feature is gated earlier by the capability check, so the
# specific rule under test is unreachable and the assertion does not apply.
requires_postgres = pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL-only feature")


def ids(queryset):
    """The ``id`` column of every row, in order."""
    return list(queryset.values_list("id", flat=True))


def assert_sql_contains(queryset, *fragments):
    """Assert the compiled SQL contains each fragment (case-insensitive)."""
    sql, _ = queryset.query.sql_with_params()
    normalized = " ".join(sql.upper().split())
    for fragment in fragments:
        assert fragment.upper() in normalized
