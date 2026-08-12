def ids(queryset):
    """The ``id`` column of every row, in order."""
    return list(queryset.values_list("id", flat=True))


def assert_sql_contains(queryset, *fragments):
    """Assert the compiled SQL contains each fragment (case-insensitive)."""
    sql, _ = queryset.query.sql_with_params()
    normalized = " ".join(sql.upper().split())
    for fragment in fragments:
        assert fragment.upper() in normalized
