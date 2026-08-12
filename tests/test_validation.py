from django.test import TestCase

from django_safeql.exceptions import ValidationError
from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.schema_factory import make_schema


class SQLValidationTestCase(TestCase):
    def setUp(self):
        self.transpiler = SQLToQuerySetTranspiler(make_schema())

    def test_validation_rejects_unknown_table(self):
        with self.assertRaisesRegex(ValidationError, "Unknown table"):
            self.transpiler.to_ast("SELECT * FROM unknown_table")

    def test_validation_rejects_star_on_unknown_table(self):
        with self.assertRaisesRegex(ValidationError, "Unknown table"):
            self.transpiler.to_ast("SELECT unknown_table.* FROM book")

    def test_validation_rejects_non_base_from(self):
        with self.assertRaisesRegex(ValidationError, "FROM must use base table"):
            self.transpiler.to_ast("SELECT publisher.* FROM publisher")

    def test_validation_rejects_unknown_field(self):
        with self.assertRaisesRegex(ValidationError, "Unknown field"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                WHERE book.nope = 'x'
            """)

    def test_validation_rejects_having_without_group_by(self):
        with self.assertRaisesRegex(ValidationError, "HAVING requires GROUP BY"):
            self.transpiler.to_ast("""
                SELECT COUNT(*) AS total
                FROM book
                HAVING COUNT(*) > 0
            """)

    def test_validation_rejects_unsupported_function(self):
        with self.assertRaisesRegex(ValidationError, "Unsupported SQL function"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                WHERE MD5(book.title) = 'abc'
            """)

    def test_validation_rejects_bad_function_arity(self):
        with self.assertRaisesRegex(ValidationError, "concat expects at least 2 arguments"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                WHERE CONCAT(book.title) = 'x'
            """)

    def test_validation_rejects_unknown_json_field(self):
        with self.assertRaisesRegex(ValidationError, "Field is not declared as JSON"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                WHERE book.title->>'x' = 'y'
            """)

    def test_validation_rejects_excessive_limit(self):
        with self.assertRaisesRegex(ValidationError, "LIMIT exceeds"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                LIMIT 5000
            """)


class SQLGroupByCoverageValidationTestCase(TestCase):
    """SQL-standard GROUP BY coverage: every non-aggregate expression in
    SELECT/HAVING/ORDER BY must be covered by the GROUP BY, or be rejected."""

    def setUp(self):
        self.transpiler = SQLToQuerySetTranspiler(make_schema())

    def test_rejects_bare_ungrouped_column_in_select(self):
        with self.assertRaisesRegex(ValidationError, "must appear in GROUP BY"):
            self.transpiler.to_ast("""
                SELECT book.status, book.pages, COUNT(*) AS c
                FROM book
                GROUP BY book.status
            """)

    def test_rejects_expression_with_ungrouped_leaf_in_select(self):
        with self.assertRaisesRegex(ValidationError, "must appear in GROUP BY"):
            self.transpiler.to_ast("""
                SELECT book.status, (book.pages + 1) AS p, COUNT(*) AS c
                FROM book
                GROUP BY book.status
            """)

    def test_rejects_having_on_ungrouped_non_aggregate(self):
        with self.assertRaisesRegex(ValidationError, "HAVING may only reference"):
            self.transpiler.to_ast("""
                SELECT book.status, COUNT(*) AS c
                FROM book
                GROUP BY book.status
                HAVING book.pages > 10
            """)

    def test_rejects_order_by_on_ungrouped_non_aggregate(self):
        with self.assertRaisesRegex(ValidationError, "ORDER BY may only reference"):
            self.transpiler.to_ast("""
                SELECT book.status, COUNT(*) AS c
                FROM book
                GROUP BY book.status
                ORDER BY book.pages DESC
            """)

    def test_rejects_star_with_group_by(self):
        with self.assertRaisesRegex(ValidationError, "GROUP BY"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                GROUP BY book.status
            """)

    def test_rejects_order_by_bare_column_on_aggregate_without_group_by(self):
        with self.assertRaisesRegex(ValidationError, "ORDER BY may only reference"):
            self.transpiler.to_ast("""
                SELECT COUNT(*) AS c
                FROM book
                ORDER BY book.pages DESC
            """)

    def test_rejects_mixed_aggregate_and_bare_column_without_group_by(self):
        with self.assertRaisesRegex(ValidationError, "must appear in GROUP BY"):
            self.transpiler.to_ast("""
                SELECT book.status, COUNT(*) AS c
                FROM book
            """)


class SQLLateralValidationTestCase(TestCase):
    def setUp(self):
        self.transpiler = SQLToQuerySetTranspiler(make_schema())

    # --- Unsupported cases ---

    def test_lateral_rejects_unsupported_set_returning_function(self):
        with self.assertRaisesRegex(ValidationError, "is not supported"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                CROSS JOIN LATERAL generate_series(1, 10) AS n
            """)

    def test_lateral_jsonb_array_elements_passes_validation(self):
        self.transpiler.to_ast("""
            SELECT book.id, SUM((item->>'amount')::numeric) AS total
            FROM book
            CROSS JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item
            GROUP BY book.id
        """)

    def test_lateral_rejects_unknown_inner_table(self):
        with self.assertRaisesRegex(ValidationError, "Unknown table"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT x.name FROM unknown_table x WHERE x.id = book.id LIMIT 1
                ) AS lat ON true
            """)

    def test_lateral_rejects_unknown_inner_field_in_where(self):
        with self.assertRaisesRegex(ValidationError, "Unknown field"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p WHERE p.badfield = 'x' LIMIT 1
                ) AS pinfo ON true
            """)

    def test_lateral_rejects_join_in_subquery(self):
        # Regression test: a JOIN inside a LATERAL subquery used to be silently
        # dropped by codegen (never applied) instead of being rejected.
        with self.assertRaisesRegex(ValidationError, "JOIN is not supported"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p
                    JOIN publisher q ON p.publisher_id = q.id AND q.is_active = true
                    WHERE p.id = book.author_id
                    LIMIT 1
                ) AS pinfo ON true
            """)

    def test_lateral_rejects_group_by_in_subquery(self):
        # Regression test: GROUP BY inside a LATERAL subquery used to be silently
        # dropped by codegen instead of being rejected.
        with self.assertRaisesRegex(ValidationError, "GROUP BY is not supported"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p WHERE p.publisher_id = book.publisher_id
                    GROUP BY p.name
                    LIMIT 1
                ) AS pinfo ON true
            """)

    def test_lateral_rejects_distinct_in_subquery(self):
        with self.assertRaisesRegex(ValidationError, "DISTINCT is not supported"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT DISTINCT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
                ) AS pinfo ON true
            """)

    def test_lateral_rejects_misleading_limit_in_subquery(self):
        # Regression test: a LIMIT other than 1 used to be silently coerced to 1 by
        # codegen instead of being rejected — the written LIMIT was pure fiction.
        with self.assertRaisesRegex(ValidationError, "LIMIT must be omitted or set to 1"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 5
                ) AS pinfo ON true
            """)

    def test_exists_rejects_join_in_subquery(self):
        with self.assertRaisesRegex(ValidationError, "JOIN is not supported"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                WHERE EXISTS (
                    SELECT 1 FROM author p
                    JOIN publisher q ON p.publisher_id = q.id
                    WHERE p.id = book.author_id
                )
            """)

    def test_lateral_rejects_json_path_on_outer_ref(self):
        # Regression test: a JSON path applied to an outer-table correlation used to
        # crash with an unhandled KeyError instead of a clean ValidationError.
        with self.assertRaisesRegex(ValidationError, "JSON path access on a reference to the outer"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p WHERE p.name = book.metadata->>'source' LIMIT 1
                ) AS pinfo ON true
            """)

    def test_exists_rejects_json_path_on_outer_ref(self):
        with self.assertRaisesRegex(ValidationError, "JSON path access on a reference to the outer"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                WHERE EXISTS (
                    SELECT 1 FROM author p WHERE p.name = book.metadata->>'source'
                )
            """)

    def test_lateral_rejects_unwhitelisted_outer_field_in_where(self):
        # Regression test: an outer-table column referenced from inside a LATERAL
        # subquery's WHERE clause must be checked against the outer table's
        # allowed_fields, just like any other column reference.
        with self.assertRaisesRegex(ValidationError, "Unknown field: book.print_run"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                LEFT JOIN LATERAL (
                    SELECT p.name FROM author p WHERE p.id = book.print_run LIMIT 1
                ) AS pinfo ON true
            """)

    def test_exists_rejects_unwhitelisted_outer_field_in_where(self):
        # Same bypass, via EXISTS instead of LATERAL.
        with self.assertRaisesRegex(ValidationError, "Unknown field: book.print_run"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                WHERE EXISTS (
                    SELECT 1 FROM author p WHERE p.id = book.print_run
                )
            """)

    def test_exists_rejects_unknown_inner_table(self):
        with self.assertRaisesRegex(ValidationError, "Unknown table"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                WHERE EXISTS (
                    SELECT 1 FROM unknown_table x WHERE x.id = book.id
                )
            """)

    def test_exists_rejects_unknown_inner_field_in_where(self):
        with self.assertRaisesRegex(ValidationError, "Unknown field"):
            self.transpiler.to_ast("""
                SELECT book.id FROM book
                WHERE EXISTS (
                    SELECT 1 FROM author p WHERE p.nope = 'x'
                )
            """)

    # --- Supported cases ---

    def test_lateral_valid_left_join_passes(self):
        self.transpiler.to_ast("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
            ) AS pinfo ON true
        """)

    def test_exists_valid_passes(self):
        self.transpiler.to_ast("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p WHERE p.id = book.author_id AND p.name = 'Orders'
            )
        """)
