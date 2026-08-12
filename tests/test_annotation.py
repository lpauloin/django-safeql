from django.test import TestCase

from django_safeql.exceptions import ValidationError
from django_safeql.nodes import BinaryOp, Column, JsonHasAllKeys, JsonHasAnyKeys, JsonHasKey, JsonPath
from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.schema_factory import make_schema


class SQLAnnotationTestCase(TestCase):
    def setUp(self):
        self.transpiler = SQLToQuerySetTranspiler(make_schema())

    def collect_comparison_left_columns(self, node):
        columns = []
        if isinstance(node, BinaryOp) and isinstance(node.left, Column):
            columns.append(node.left)
        for child in node.children():
            if child is not None:
                columns.extend(self.collect_comparison_left_columns(child))
        return columns

    def test_annotation_column_paths(self):
        ast = self.transpiler.to_ast("""
            SELECT book.*
            FROM book
            JOIN publisher ON book.publisher_id = publisher.id
            JOIN author ON book.author_id = author.id
            WHERE publisher.name = 'Acme'
              AND author.name = 'Invoices'
              AND book.status = 'PARSED_OK'
        """)

        paths = {column.annotations["django_path"] for column in self.collect_comparison_left_columns(ast.where)}
        self.assertEqual(paths, {"publisher__name", "author__name", "status"})

    def test_annotation_json_path_schema(self):
        ast = self.transpiler.to_ast("""
            SELECT book.*
            FROM book
            WHERE book.details->'summary'->>'total' = '120.50'
        """)

        json_path = ast.where.left
        self.assertIsInstance(json_path, JsonPath)
        self.assertEqual(json_path.annotations["django_path"], "details__summary__total")
        self.assertEqual(json_path.annotations["json_type"], "number")
        self.assertEqual(json_path.annotations["json_schema"]["description"], "Total amount")

    def test_annotation_json_array_path_schema(self):
        ast = self.transpiler.to_ast("""
            SELECT book.*
            FROM book
            WHERE book.details->'chapters'->0->>'amount' = '100.50'
        """)

        json_path = ast.where.left
        self.assertEqual(json_path.annotations["django_path"], "details__chapters__0__amount")
        self.assertEqual(json_path.annotations["json_type"], "number")

    def test_annotation_alias_table(self):
        ast = self.transpiler.to_ast("""
            SELECT d.*
            FROM book AS d
            JOIN author AS p ON d.author_id = p.id
            WHERE p.name = 'Vernor Vinge'
        """)
        self.assertEqual(ast.where.left.annotations["django_path"], "author__name")

    def test_annotation_rejects_unknown_json_path(self):
        with self.assertRaisesRegex(ValidationError, "Unknown JSON path"):
            self.transpiler.to_ast("""
                SELECT book.*
                FROM book
                WHERE book.details->'summary'->>'missing' = 'x'
            """)

    def test_annotation_allof_json_schema_resolves_path(self):
        from django_safeql.json_schema import JsonSchemaResolver

        resolver = JsonSchemaResolver()
        schema = {
            "allOf": [
                {"type": "object", "properties": {"amount": {"type": "number"}}},
                {"type": "object", "properties": {"label": {"type": "string"}}},
            ]
        }
        self.assertEqual(resolver.resolve_path(schema, ["amount"]), {"type": "number"})
        self.assertEqual(resolver.resolve_path(schema, ["label"]), {"type": "string"})
        self.assertIsNone(resolver.resolve_path(schema, ["missing"]))


class SQLAnnotationCompleteSyntaxTestCase(TestCase):
    def setUp(self):
        self.transpiler = SQLToQuerySetTranspiler(make_schema())

    def test_annotation_select_aliases_are_registered_on_query(self):
        ast = self.transpiler.to_ast("""
            SELECT LOWER(book.title) AS normalized_title,
                   book.pages * 2 AS weighted_pages
            FROM book
            ORDER BY normalized_title ASC
        """)
        aliases = ast.annotations["select_aliases"]
        self.assertEqual(set(aliases), {"normalized_title", "weighted_pages"})
        self.assertEqual(ast.order_by[0].expression.annotations["select_alias"], "normalized_title")
        self.assertEqual(ast.order_by[0].expression.annotations["django_path"], "normalized_title")

    def test_annotation_group_by_and_having_aggregate_alias(self):
        ast = self.transpiler.to_ast("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            HAVING COUNT(*) >= 1
            ORDER BY total DESC
        """)
        self.assertEqual(ast.group_by[0].annotations["django_path"], "author__id")
        self.assertEqual(ast.select.columns[1].annotations["alias"], "total")
        self.assertEqual(ast.having.left.annotations["aggregate_function"], "count")
        self.assertEqual(ast.order_by[0].expression.annotations["select_alias"], "total")

    def test_annotation_casted_json_numeric_path(self):
        ast = self.transpiler.to_ast("""
            SELECT book.*
            FROM book
            WHERE (book.details->'summary'->>'total')::numeric > 100
        """)
        cast_node = ast.where.left
        self.assertEqual(cast_node.annotations["cast_type"], "decimal")
        self.assertEqual(cast_node.expression.annotations["django_path"], "details__summary__total")
        self.assertEqual(cast_node.expression.annotations["json_type"], "number")

    def test_annotation_json_has_key_operators(self):
        queries = [
            ("book.metadata ? 'source'", JsonHasKey),
            ("book.metadata ?| array['source', 'priority']", JsonHasAnyKeys),
            ("book.metadata ?& array['source', 'priority']", JsonHasAllKeys),
        ]
        for where_sql, expected_type in queries:
            with self.subTest(where=where_sql):
                ast = self.transpiler.to_ast(f"SELECT book.* FROM book WHERE {where_sql}")
                self.assertIsInstance(ast.where, expected_type)
                self.assertEqual(ast.where.left.annotations["django_path"], "metadata")
                self.assertTrue(ast.where.left.annotations["is_json_field"])

    def test_annotation_column_to_column_comparison_paths(self):
        ast = self.transpiler.to_ast("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.publisher_id = author.publisher_id
        """)
        self.assertEqual(ast.where.left.annotations["django_path"], "publisher_id")
        self.assertEqual(ast.where.right.annotations["django_path"], "author__publisher_id")
