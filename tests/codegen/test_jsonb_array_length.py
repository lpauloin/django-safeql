from tests.helpers import ids


def test_in_select(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_array_length(book.metadata->'lines') AS line_count
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["line_count"] == 2


def test_empty_array(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_array_length(book.metadata->'lines') AS line_count
        FROM book WHERE book.id = {library.d2.id}
    """)
    assert list(qs)[0]["line_count"] == 0


def test_in_where_filter(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_array_length(book.metadata->'lines') > 0
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id]


def test_in_where_equals(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_array_length(book.metadata->'lines') = 2
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id]


def test_in_aggregate(library):
    qs = library.transpiler.to_queryset("""
        SELECT SUM(jsonb_array_length(book.metadata->'lines')) AS total_lines
        FROM book
        WHERE book.metadata ? 'lines'
    """)
    assert list(qs)[0]["total_lines"] == 2


def test_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT jsonb_array_length(book.metadata->'lines') AS line_count,
               COUNT(*) AS total
        FROM book
        WHERE book.metadata ? 'lines'
        GROUP BY line_count
        ORDER BY line_count ASC
    """)
    by_count = {r["line_count"]: r["total"] for r in qs}
    assert by_count[0] == 1
    assert by_count[2] == 1


# --- unqualified column (SQLGlot Lambda bug path) ---


def test_unqualified_in_select(library):
    # SQLGlot parses unqualified col->'key' as Lambda inside Anonymous fn calls;
    # visit_Lambda must convert it back to JsonPath.
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_array_length(metadata->'lines') AS line_count
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["line_count"] == 2


def test_unqualified_in_where(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_array_length(metadata->'lines') > 0
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id]


def test_unqualified_in_aggregate(library):
    qs = library.transpiler.to_queryset("""
        SELECT SUM(jsonb_array_length(metadata->'lines')) AS total_lines
        FROM book
        WHERE book.metadata ? 'lines'
    """)
    assert list(qs)[0]["total_lines"] == 2


def test_unqualified_chained_path(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_array_length(metadata->'lines') AS line_count
        FROM book WHERE book.id = {library.d2.id}
    """)
    assert list(qs)[0]["line_count"] == 0


def test_jsonb_typeof_unqualified(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_typeof(metadata->'lines') AS t
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["t"] == "array"
