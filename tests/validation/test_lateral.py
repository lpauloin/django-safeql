import pytest

from django_safeql.exceptions import ValidationError

# --- Unsupported cases ---


def test_rejects_unsupported_set_returning_function(transpiler):
    with pytest.raises(ValidationError, match="is not supported"):
        transpiler.to_ast("SELECT book.id FROM book CROSS JOIN LATERAL generate_series(1, 10) AS n")


def test_jsonb_array_elements_passes_validation(transpiler):
    transpiler.to_ast("""
        SELECT book.id, SUM((item->>'amount')::numeric) AS total
        FROM book
        CROSS JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item
        GROUP BY book.id
    """)


def test_rejects_collection_aggregate_over_srf(transpiler):
    with pytest.raises(ValidationError, match="not supported over LATERAL set-returning"):
        transpiler.to_ast("""
            SELECT book.id, ARRAY_AGG((item->>'amount')::numeric) AS a
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            GROUP BY book.id
        """)


def test_rejects_srf_element_outside_aggregate(transpiler):
    with pytest.raises(ValidationError, match="may only be used inside an aggregate"):
        transpiler.to_ast("""
            SELECT book.id, (item->>'amount') AS a
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        """)


def test_subquery_rejects_non_scalar_aggregate(transpiler):
    with pytest.raises(ValidationError, match="is not supported inside LATERAL/EXISTS subqueries"):
        transpiler.to_ast("""
            SELECT book.id, x.n AS n
            FROM book
            LEFT JOIN LATERAL (
                SELECT ARRAY_AGG(p.name) AS n FROM author p WHERE p.id = book.author_id
            ) AS x ON true
        """)


def test_rejects_unknown_inner_table(transpiler):
    with pytest.raises(ValidationError, match="Unknown table"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT x.name FROM unknown_table x WHERE x.id = book.id LIMIT 1
            ) AS lat ON true
        """)


def test_rejects_unknown_inner_field_in_where(transpiler):
    with pytest.raises(ValidationError, match="Unknown field"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.badfield = 'x' LIMIT 1
            ) AS pinfo ON true
        """)


def test_rejects_join_in_subquery(transpiler):
    # A JOIN inside a LATERAL subquery used to be silently dropped by codegen.
    with pytest.raises(ValidationError, match="JOIN is not supported"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p
                JOIN publisher q ON p.publisher_id = q.id AND q.is_active = true
                WHERE p.id = book.author_id
                LIMIT 1
            ) AS pinfo ON true
        """)


def test_rejects_group_by_in_subquery(transpiler):
    # GROUP BY inside a LATERAL subquery used to be silently dropped by codegen.
    with pytest.raises(ValidationError, match="GROUP BY is not supported"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.publisher_id = book.publisher_id
                GROUP BY p.name
                LIMIT 1
            ) AS pinfo ON true
        """)


def test_rejects_distinct_in_subquery(transpiler):
    with pytest.raises(ValidationError, match="DISTINCT is not supported"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT DISTINCT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
            ) AS pinfo ON true
        """)


def test_rejects_misleading_limit_in_subquery(transpiler):
    # A LIMIT other than 1 used to be silently coerced to 1 by codegen.
    with pytest.raises(ValidationError, match="LIMIT must be omitted or set to 1"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 5
            ) AS pinfo ON true
        """)


def test_exists_rejects_join_in_subquery(transpiler):
    with pytest.raises(ValidationError, match="JOIN is not supported"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p
                JOIN publisher q ON p.publisher_id = q.id
                WHERE p.id = book.author_id
            )
        """)


def test_rejects_json_path_on_outer_ref(transpiler):
    # A JSON path on an outer-table correlation used to crash with a KeyError.
    with pytest.raises(ValidationError, match="JSON path access on a reference to the outer"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.name = book.metadata->>'source' LIMIT 1
            ) AS pinfo ON true
        """)


def test_exists_rejects_json_path_on_outer_ref(transpiler):
    with pytest.raises(ValidationError, match="JSON path access on a reference to the outer"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p WHERE p.name = book.metadata->>'source'
            )
        """)


def test_rejects_unwhitelisted_outer_field_in_where(transpiler):
    # An outer-table column referenced from inside a LATERAL subquery must be
    # checked against the outer table's allowed_fields, like any other column.
    with pytest.raises(ValidationError, match="Unknown field: book.print_run"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.id = book.print_run LIMIT 1
            ) AS pinfo ON true
        """)


def test_exists_rejects_unwhitelisted_outer_field_in_where(transpiler):
    with pytest.raises(ValidationError, match="Unknown field: book.print_run"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p WHERE p.id = book.print_run
            )
        """)


def test_exists_rejects_unknown_inner_table(transpiler):
    with pytest.raises(ValidationError, match="Unknown table"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM unknown_table x WHERE x.id = book.id
            )
        """)


def test_exists_rejects_unknown_inner_field_in_where(transpiler):
    with pytest.raises(ValidationError, match="Unknown field"):
        transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p WHERE p.nope = 'x'
            )
        """)


# --- Supported cases ---


def test_valid_left_join_passes(transpiler):
    transpiler.to_ast("""
        SELECT book.id, pinfo.name AS author_name
        FROM book
        LEFT JOIN LATERAL (
            SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
        ) AS pinfo ON true
    """)


def test_exists_valid_passes(transpiler):
    transpiler.to_ast("""
        SELECT book.id FROM book
        WHERE EXISTS (
            SELECT 1 FROM author p WHERE p.id = book.author_id AND p.name = 'Orders'
        )
    """)
