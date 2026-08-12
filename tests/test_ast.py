from django.test import TestCase

from django_safeql.ast import SQLGlotParser
from django_safeql.nodes import (
    Aggregate,
    Alias,
    And,
    ArithmeticOp,
    BinaryOp,
    CaseExpr,
    CastExpr,
    Column,
    FunctionCall,
    JsonContains,
    JsonHasAllKeys,
    JsonHasAnyKeys,
    JsonHasKey,
    JsonPath,
    LateralJoin,
    Literal,
    Not,
    Query,
)


class SQLAstParserTestCase(TestCase):
    def setUp(self):
        self.parser = SQLGlotParser()

    def parse(self, sql):
        return self.parser.parse(sql)

    def test_ast_simple_select_where_order_limit(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE book.status = 'PARSED_OK'
            ORDER BY book.created_at DESC
            LIMIT 10
        """)

        self.assertIsInstance(ast, Query)
        self.assertEqual(ast.from_.table, "book")
        self.assertIsInstance(ast.where, BinaryOp)
        self.assertEqual(ast.where.op, "=")
        self.assertIsInstance(ast.where.left, Column)
        self.assertEqual(ast.where.left.table, "book")
        self.assertEqual(ast.where.left.name, "status")
        self.assertIsInstance(ast.where.right, Literal)
        self.assertEqual(ast.where.right.value, "PARSED_OK")
        self.assertEqual(len(ast.order_by), 1)
        self.assertTrue(ast.order_by[0].desc)
        self.assertEqual(ast.limit, 10)

    def test_ast_boolean_expression(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE book.status = 'PARSED_OK'
              AND (author.name = 'Invoices' OR publisher.name = 'Acme')
        """)
        self.assertIsInstance(ast.where, And)
        self.assertIsInstance(ast.where.left, BinaryOp)

    def test_ast_group_by_having_aggregate_alias(self):
        ast = self.parse("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            HAVING COUNT(*) > 10
            ORDER BY total DESC
        """)
        self.assertEqual(len(ast.group_by), 1)
        self.assertEqual(ast.group_by[0].table, "author")
        self.assertEqual(ast.group_by[0].name, "id")
        self.assertIsInstance(ast.having, BinaryOp)
        self.assertIsInstance(ast.having.left, Aggregate)
        self.assertTrue(any(isinstance(expr, Alias) for expr in ast.select.columns))

    def test_ast_math_expression(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE book.pages * 2 + 1 > 5
        """)
        self.assertIsInstance(ast.where.left, ArithmeticOp)
        self.assertEqual(ast.where.left.op, "+")
        self.assertIsInstance(ast.where.left.left, ArithmeticOp)
        self.assertEqual(ast.where.left.left.op, "*")

    def test_ast_string_functions(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE LOWER(TRIM(book.filename)) = 'invoice-a.pdf'
        """)
        self.assertIsInstance(ast.where.left, FunctionCall)
        self.assertEqual(ast.where.left.name, "lower")
        self.assertIsInstance(ast.where.left.args[0], FunctionCall)
        self.assertEqual(ast.where.left.args[0].name, "trim")

    def test_ast_json_path_extract_text(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE book.result->'invoice'->>'currency' = 'EUR'
        """)
        self.assertIsInstance(ast.where.left, JsonPath)
        self.assertEqual(ast.where.left.base.table, "book")
        self.assertEqual(ast.where.left.base.name, "result")
        self.assertEqual(ast.where.left.path, ["invoice", "currency"])
        self.assertTrue(ast.where.left.returns_text)

    def test_ast_json_array_path(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE book.result->'lines'->0->>'amount' = '100.50'
        """)
        self.assertIsInstance(ast.where.left, JsonPath)
        self.assertEqual(ast.where.left.path, ["lines", 0, "amount"])

    def test_ast_cast_json_numeric(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE (book.result->'invoice'->>'total')::numeric > 100
        """)
        self.assertIsInstance(ast.where.left, CastExpr)
        self.assertIsInstance(ast.where.left.expression, JsonPath)

    def test_ast_case_when_expression(self):
        ast = self.parse("""
            SELECT SUM(CASE WHEN book.status = 'PARSEDOK' THEN 1 ELSE 0 END) AS parsed_ok
            FROM book
        """)
        alias = ast.select.columns[0]
        self.assertIsInstance(alias.expression, Aggregate)
        self.assertIsInstance(alias.expression.expression, CaseExpr)
        self.assertEqual(len(alias.expression.expression.whens), 1)


class SQLAstCompleteSyntaxTestCase(TestCase):
    def setUp(self):
        self.parser = SQLGlotParser()

    def parse(self, sql):
        return self.parser.parse(sql)

    def test_ast_distinct_and_plain_selected_columns(self):
        ast = self.parse("""
            SELECT DISTINCT book.status, author.name
            FROM book
            JOIN author ON book.author_id = author.id
        """)
        self.assertTrue(ast.distinct)
        self.assertEqual([c.name for c in ast.select.columns], ["status", "name"])
        self.assertEqual([c.table for c in ast.select.columns], ["book", "author"])

    def test_ast_in_not_and_is_not_null(self):
        # sqlglot <= 30.8 represents "x IS NOT NULL" as Not(BinaryOp(IS NULL));
        # newer sqlglot versions emit a single BinaryOp(IS NOT NULL) instead.
        # Both shapes are valid output of the parser and both are accepted by
        # validation/codegen, so this test accepts either.
        def is_not_null(node):
            if isinstance(node, BinaryOp):
                return node.op == "IS NOT NULL"
            if isinstance(node, Not) and isinstance(node.expr, BinaryOp):
                return node.expr.op == "IS NULL"
            return False

        def is_in(node):
            return isinstance(node, Not) and isinstance(node.expr, BinaryOp) and node.expr.op == "IN"

        ast = self.parse("""
            SELECT book.*
            FROM book
            WHERE NOT book.status IN ('FAILED')
              AND book.created_at IS NOT NULL
        """)
        self.assertIsInstance(ast.where, And)
        self.assertTrue(is_not_null(ast.where.right))
        self.assertTrue(is_in(ast.where.left))

    def test_ast_column_to_column_comparison(self):
        ast = self.parse("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.publisher_id = author.publisher_id
        """)
        self.assertIsInstance(ast.where, BinaryOp)
        self.assertIsInstance(ast.where.left, Column)
        self.assertIsInstance(ast.where.right, Column)
        self.assertEqual(ast.where.left.name, "publisher_id")
        self.assertEqual(ast.where.right.name, "publisher_id")

    def test_ast_select_expression_aliases(self):
        ast = self.parse("""
            SELECT LOWER(book.filename) AS normalized_filename,
                   book.pages * 2 AS weighted_pages
            FROM book
        """)
        self.assertEqual(len(ast.select.columns), 2)
        self.assertIsInstance(ast.select.columns[0], Alias)
        self.assertIsInstance(ast.select.columns[0].expression, FunctionCall)
        self.assertEqual(ast.select.columns[0].alias, "normalized_filename")
        self.assertIsInstance(ast.select.columns[1].expression, ArithmeticOp)

    def test_ast_json_key_operators(self):
        has_key = self.parse("""
            SELECT book.* FROM book WHERE book.metadata ? 'source'
        """)
        has_any = self.parse("""
            SELECT book.* FROM book WHERE book.metadata ?| array['source', 'priority']
        """)
        has_all = self.parse("""
            SELECT book.* FROM book WHERE book.metadata ?& array['source', 'priority']
        """)

        self.assertIsInstance(has_key.where, JsonHasKey)
        self.assertIsInstance(has_any.where, JsonHasAnyKeys)
        self.assertIsInstance(has_all.where, JsonHasAllKeys)

    def test_ast_json_contains_operator(self):

        ast = self.parse("""
            SELECT book.* FROM book WHERE book.metadata @> '{"source": "email"}'
        """)
        self.assertIsInstance(ast.where, JsonContains)

    def test_ast_json_path_inside_function_single(self):
        # SQLGlot parses col->'key' as Lambda when used as a function argument.
        ast = self.parse("SELECT jsonb_array_length(result_json->'line_items') FROM book")
        fn = ast.select.columns[0]
        self.assertIsInstance(fn, FunctionCall)
        self.assertEqual(fn.name, "jsonb_array_length")
        arg = fn.args[0]
        self.assertIsInstance(arg, JsonPath)
        self.assertEqual(arg.path, ["line_items"])
        self.assertFalse(arg.returns_text)

    def test_ast_json_path_inside_function_chained(self):
        ast = self.parse("SELECT jsonb_array_length(result_json->'a'->'b') FROM book")
        fn = ast.select.columns[0]
        arg = fn.args[0]
        self.assertIsInstance(arg, JsonPath)
        self.assertEqual(arg.path, ["a", "b"])

    def test_ast_json_path_inside_aggregate(self):
        ast = self.parse("SELECT SUM(jsonb_array_length(result_json->'lines')) FROM book")
        agg = ast.select.columns[0]
        self.assertIsInstance(agg, Aggregate)
        fn = agg.expression
        self.assertIsInstance(fn, FunctionCall)
        self.assertEqual(fn.args[0].path, ["lines"])

    def test_ast_complete_string_function_surface(self):
        function_sql = {
            "upper": "UPPER(book.filename)",
            "ltrim": "LTRIM(book.filename)",
            "rtrim": "RTRIM(book.filename)",
            "length": "LENGTH(book.filename)",
            "substring": "SUBSTRING(book.filename FROM 1 FOR 7)",
            "concat": "CONCAT(book.filename, book.status)",
            "coalesce": "COALESCE(book.filename, 'fallback')",
            "replace": "REPLACE(book.filename, 'invoice', 'doc')",
            "strpos": "STRPOS(book.filename, 'pdf')",
        }
        for expected_name, sql_expr in function_sql.items():
            with self.subTest(function=expected_name):
                ast = self.parse(f"SELECT book.* FROM book WHERE {sql_expr} IS NOT NULL")
                expr = ast.where.expr.left if hasattr(ast.where, "expr") else ast.where.left
                self.assertIsInstance(expr, FunctionCall)
                self.assertEqual(expr.name, expected_name)


class NodesInvariantTestCase(TestCase):
    def test_children_never_returns_none(self):
        ast = SQLGlotParser().parse("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.status = 'PARSED_OK' AND book.created_at IS NOT NULL
            GROUP BY author.id
            HAVING COUNT(*) > 1
            ORDER BY total DESC
            LIMIT 5
        """)

        def walk(node):
            for child in node.children():
                self.assertIsNotNone(child, f"{node.__class__.__name__}.children() returned None")
                walk(child)

        walk(ast)

    def test_lateral_join_requires_exactly_one_of_fn_call_or_subquery(self):

        with self.assertRaises(ValueError):
            LateralJoin(fn_call=None, subquery=None)
        with self.assertRaises(ValueError):
            LateralJoin(fn_call=FunctionCall(name="jsonb_array_elements"), subquery=Query())
