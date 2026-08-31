from django.db import connection

from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.helpers import assert_sql_contains, ids
from tests.schema_factory import make_codegen_schema


def test_select_star_returns_matching_rows(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_select_star_expands_only_allowed_fields(library):
    schema = make_codegen_schema()
    schema.tables["book"].allowed_fields = {"id", "title", "status"}
    transpiler = SQLToQuerySetTranspiler(schema, target=connection.vendor)

    qs = transpiler.to_queryset(f"SELECT book.* FROM book WHERE book.id = {library.d1.id}")
    assert set(list(qs)[0].keys()) == {"id", "title", "status"}


def test_select_joined_table_star_expands_only_allowed_fields(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT author.*
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE book.id = {library.d1.id}
    """)
    assert set(list(qs)[0].keys()) == {"author__id", "author__name", "author__publisher_id"}


def test_select_specific_columns(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, book.status
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE book.status = 'PUBLISHED'
        ORDER BY author.id ASC
    """)
    rows = list(qs)
    assert set(rows[0].keys()) == {"author__id", "status"}


def test_select_alias_without_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT LOWER(book.title) AS normalized_name,
               book.print_run * 2 AS weighted_credits
        FROM book
        WHERE book.title = 'letters-one.txt'
    """)
    assert_sql_contains(qs, "LOWER", "WEIGHTED_CREDITS")
    assert list(qs) == [{"normalized_name": "letters-one.txt", "weighted_credits": 4}]


def test_select_alias_used_in_order_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.print_run * 2 AS double_credits
        FROM book
        ORDER BY double_credits DESC
    """)
    credits = [row["double_credits"] for row in qs]
    assert credits == sorted(credits, reverse=True)


def test_select_alias_used_in_having(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        HAVING COUNT(*) >= 2
        ORDER BY total DESC
    """)
    assert list(qs) == [{"author__id": library.author_x.id, "total": 2}]


def test_select_distinct(library):
    qs = library.transpiler.to_queryset("SELECT DISTINCT book.status FROM book ORDER BY book.status ASC")
    assert_sql_contains(qs, "SELECT DISTINCT")
    assert list(qs) == [{"status": "PUBLISHED"}, {"status": "REJECTED"}]


def test_select_limit(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC LIMIT 1"
    )
    assert_sql_contains(qs, "LIMIT")
    assert ids(qs) == [library.d1.id]


def test_select_order_by_desc(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id DESC LIMIT 2"
    )
    assert ids(qs) == [library.d4.id, library.d2.id]
