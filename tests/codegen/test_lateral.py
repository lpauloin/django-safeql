import pytest

from tests.helpers import ids
from tests.testapp.models import Book


def test_left_join_lateral_annotates_author_name(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        LEFT JOIN LATERAL (
            SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
        ) AS pinfo ON true
        ORDER BY book.id ASC
    """)
    rows = {r["id"]: r["author_name"] for r in qs}
    assert rows[library.d1.id] == "Ada Lovelace"
    assert rows[library.d2.id] == "Ada Lovelace"
    assert rows[library.d3.id] == "Charles Babbage"
    assert rows[library.d4.id] == "Ada Lovelace"


def test_left_join_lateral_uses_subquery_not_raw_sql(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        LEFT JOIN LATERAL (
            SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
        ) AS pinfo ON true
    """)
    sql, _ = qs.query.sql_with_params()
    assert "SELECT" in sql.upper()
    assert "LATERAL" not in sql.upper()


def test_cross_join_lateral_acts_as_inner_join(library):
    # The inner WHERE restricts to 'Charles Babbage', so only d3 survives the filter.
    qs = library.transpiler.to_queryset("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        CROSS JOIN LATERAL (
            SELECT p.name FROM author p
            WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
            LIMIT 1
        ) AS pinfo
        ORDER BY book.id ASC
    """)
    rows = list(qs)
    assert len(rows) == 1
    assert rows[0]["id"] == library.d3.id
    assert rows[0]["author_name"] == "Charles Babbage"


def test_exists_in_where_filters_by_author_name(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id FROM book
        WHERE EXISTS (
            SELECT 1 FROM author p
            WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
        )
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d3.id]


def test_not_exists_in_where(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id FROM book
        WHERE NOT EXISTS (
            SELECT 1 FROM author p
            WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
        )
        ORDER BY book.id ASC
    """)
    assert ids(qs) == sorted([library.d1.id, library.d2.id, library.d4.id])


def test_jsonb_array_elements_sum_per_document(library):
    # d1 has lines=[{amount:"100.50"}, {amount:"20.00"}], d2 has lines=[].
    qs = library.transpiler.to_queryset("""
        SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        GROUP BY book.id
        ORDER BY book.id ASC
    """)
    rows = {r["id"]: r["total_amount"] for r in qs}
    assert library.d1.id in rows
    assert float(rows[library.d1.id]) == pytest.approx(120.50, abs=0.01)
    # d2: empty lines array -> SUM returns NULL.
    assert rows[library.d2.id] is None


def test_jsonb_array_elements_uses_correlated_subquery(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        GROUP BY book.id
    """)
    sql, _ = qs.query.sql_with_params()
    assert "jsonb_array_elements" in sql.lower()
    assert "LATERAL" not in sql.upper()


def test_jsonb_array_elements_whole_table_aggregate(library):
    # SUM across all documents: only d1 has non-empty lines (120.50).
    result = library.transpiler.to_queryset("""
        SELECT SUM((item->>'amount')::numeric) AS grand_total
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
    """)
    rows = list(result)
    assert len(rows) == 1
    assert float(rows[0]["grand_total"] or 0) == pytest.approx(120.50, abs=0.01)


def test_jsonb_array_elements_element_key_is_bound_parameter(library):
    # The JSON key ('amount') must be a bound parameter, never interpolated.
    qs = library.transpiler.to_queryset("""
        SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        GROUP BY book.id
    """)
    sql, params = qs.query.sql_with_params()
    assert "elem->>%s" in sql
    assert "->>'amount'" not in sql
    assert "amount" in params


def test_jsonb_array_elements_key_with_apostrophe(library):
    # A JSON key with a single quote must round-trip (regression for raw interpolation).
    book = Book.objects.create(
        author=library.author_x,
        status="PUBLISHED",
        title="apostrophe.txt",
        metadata={"lines": [{"o'clock": "42.00"}]},
    )
    qs = library.transpiler.to_queryset(f"""
        SELECT book.id, SUM((item->>'o''clock')::numeric) AS total_amount
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        WHERE book.id = {book.id}
        GROUP BY book.id
    """)
    rows = {r["id"]: r["total_amount"] for r in qs}
    assert float(rows[book.id]) == pytest.approx(42.00, abs=0.01)


def test_jsonb_array_elements_element_key_injection_is_neutralized(library):
    # Regression for SQL injection via the LATERAL element key: a malicious key must
    # never break out of the SQL and must appear only in params, never in the text.
    qs = library.transpiler.to_queryset("""
        SELECT book.id, SUM((item->>'x'') UNION SELECT password FROM auth_user --')::numeric) AS total
        FROM book
        LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        GROUP BY book.id
    """)
    sql, params = qs.query.sql_with_params()
    assert "UNION" not in sql.upper()
    assert "auth_user" not in sql
    assert "x') UNION SELECT password FROM auth_user --" in params
    # Executing must not raise a syntax error — the payload is an inert bound key.
    list(qs)


def test_lateral_inner_where_in_values(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        LEFT JOIN LATERAL (
            SELECT p.name FROM author p
            WHERE p.id = book.author_id
              AND p.name IN ('Ada Lovelace', 'Charles Babbage')
            LIMIT 1
        ) AS pinfo ON true
        ORDER BY book.id ASC
    """)
    rows = {r["id"]: r["author_name"] for r in qs}
    assert rows[library.d1.id] == "Ada Lovelace"
    assert rows[library.d3.id] == "Charles Babbage"


def test_lateral_correlated_with_not_condition(library):
    # _find_correlated_field must traverse Not nodes.
    qs = library.transpiler.to_queryset("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        LEFT JOIN LATERAL (
            SELECT p.name FROM author p
            WHERE p.id = book.author_id AND NOT p.name = 'Charles Babbage'
            LIMIT 1
        ) AS pinfo ON true
        ORDER BY book.id ASC
    """)
    rows = {r["id"]: r["author_name"] for r in qs}
    assert rows.get(library.d3.id) is None
    assert rows[library.d1.id] == "Ada Lovelace"
