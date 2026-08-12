from tests.helpers import ids


def test_equality(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_not_equal(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.status != 'REJECTED' ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_comparison_operators(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run > 2 ORDER BY book.id ASC")
    assert ids(qs) == [library.d2.id, library.d4.id]

    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run >= 4 ORDER BY book.id ASC")
    assert ids(qs) == [library.d2.id, library.d4.id]

    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run < 4 ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d3.id]

    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run <= 2 ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d3.id]


def test_in_operator(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.status IN ('PUBLISHED', 'REJECTED') ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]


def test_is_null_and_is_not_null(library):
    library.d1.word_count = 123
    library.d1.save(update_fields=["word_count"])

    qs_not_null = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.word_count IS NOT NULL")
    qs_null = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.word_count IS NULL ORDER BY book.id ASC"
    )
    assert ids(qs_not_null) == [library.d1.id]
    assert ids(qs_null) == [library.d2.id, library.d3.id, library.d4.id]


def test_and_or_not(library):
    qs_and = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE book.status = 'PUBLISHED' AND book.print_run >= 4
        ORDER BY book.id ASC
    """)
    assert ids(qs_and) == [library.d2.id, library.d4.id]

    qs_or = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE book.status = 'REJECTED' OR book.print_run >= 4
        ORDER BY book.id ASC
    """)
    assert ids(qs_or) == [library.d2.id, library.d3.id, library.d4.id]

    qs_not = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE NOT book.print_run < 4
        ORDER BY book.id ASC
    """)
    assert ids(qs_not) == [library.d2.id, library.d4.id]


def test_like_startswith(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.title LIKE 'letters-%' ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_like_endswith(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.title LIKE '%.txt' ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]


def test_like_contains(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.title LIKE '%memo%' ORDER BY book.id ASC")
    assert ids(qs) == [library.d3.id]


def test_ilike_case_insensitive(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.title ILIKE '%LETTERS%' ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_like_complex_internal_wildcard(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.title LIKE 'letters%.txt' ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_field_sentinel_literal_is_not_a_field_reference(library):
    # A user literal starting with the internal "__field__:" prefix must stay a
    # bound value — never become an F() field/relation reference, which would
    # bypass the table/field whitelist and join to undeclared related tables.
    qs = library.transpiler.to_queryset("SELECT book.id FROM book WHERE book.status = '__field__:author__name'")
    sql, params = qs.query.sql_with_params()
    assert "__field__:author__name" in params
    assert "JOIN" not in sql.upper()
    assert list(qs) == []


def test_like_exact_match(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.title LIKE 'letters-one.txt' ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id]
