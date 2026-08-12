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
