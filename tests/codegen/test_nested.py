from tests.helpers import assert_sql_contains, ids


def test_arithmetic_inside_aggregate(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, SUM((book.print_run + 1) * 2) AS weighted
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        ORDER BY author.id ASC
    """)
    by_author = {row["author__id"]: row for row in qs}
    assert by_author[library.author_x.id]["weighted"] == (2 + 1) * 2 + (4 + 1) * 2


def test_function_in_where_on_joined_column(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE LOWER(author.name) = 'ada lovelace' AND book.status = 'PUBLISHED'
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_cast_inside_aggregate_having(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE (book.metadata->>'total')::numeric > 80
        GROUP BY author.id
        HAVING COUNT(*) >= 1
        ORDER BY total DESC
    """)
    rows = list(qs)
    assert len(rows) > 0
    for row in rows:
        assert "total" in row


def test_nested_string_functions_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT CONCAT(UPPER(SUBSTRING(book.title FROM 1 FOR 7)), '-', book.status) AS label
        FROM book
        WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["label"] == "LETTERS-PUBLISHED"


def test_or_inside_and_with_json_and_function(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        JOIN publisher ON author.publisher_id = publisher.id
        WHERE publisher.name = 'Acme'
          AND (book.status = 'REJECTED' OR book.metadata->>'currency' = 'USD')
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d2.id, library.d3.id]


def test_full_surface(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id,
               LOWER(author.name) AS author_name,
               COUNT(*) AS total,
               SUM((book.print_run + 1) * 2) AS weighted_credits,
               AVG(book.print_run) AS average_credits,
               MIN(book.print_run) AS prints_min,
               MAX(book.print_run) AS prints_max
        FROM book
        JOIN author ON book.author_id = author.id
        JOIN publisher ON author.publisher_id = publisher.id
        WHERE publisher.name = 'Acme'
          AND book.status IN ('PUBLISHED', 'REJECTED')
          AND book.title ILIKE 'letters-%'
          AND book.metadata ? 'source'
          AND (book.metadata->>'total')::numeric >= 80
        GROUP BY author.id, author.name
        HAVING COUNT(*) >= 2
        ORDER BY total DESC, author_name ASC
        LIMIT 10
    """)
    assert_sql_contains(qs, "GROUP BY", "HAVING", "LOWER", "COUNT", "SUM", "AVG", "MIN", "MAX", "LIMIT")
    assert list(qs) == [
        {
            "author__id": library.author_x.id,
            # GROUP BY author.id, author.name — author.name is a real GROUP BY key
            # (not just the LOWER() projection of it), so it appears in the grouped
            # output alongside author_name, matching the SQL text.
            "author__name": "Ada Lovelace",
            "author_name": "ada lovelace",
            "total": 2,
            "weighted_credits": (2 + 1) * 2 + (4 + 1) * 2,
            "average_credits": 3.0,
            "prints_min": 2,
            "prints_max": 4,
        }
    ]
