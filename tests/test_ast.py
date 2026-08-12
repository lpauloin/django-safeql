import pytest

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


def parse(sql):
    return SQLGlotParser().parse(sql)


def test_simple_select_where_order_limit():
    ast = parse("""
        SELECT book.*
        FROM book
        WHERE book.status = 'PARSED_OK'
        ORDER BY book.created_at DESC
        LIMIT 10
    """)
    assert isinstance(ast, Query)
    assert ast.from_.table == "book"
    assert isinstance(ast.where, BinaryOp)
    assert ast.where.op == "="
    assert isinstance(ast.where.left, Column)
    assert ast.where.left.table == "book"
    assert ast.where.left.name == "status"
    assert isinstance(ast.where.right, Literal)
    assert ast.where.right.value == "PARSED_OK"
    assert len(ast.order_by) == 1
    assert ast.order_by[0].desc
    assert ast.limit == 10


def test_boolean_expression():
    ast = parse("""
        SELECT book.*
        FROM book
        WHERE book.status = 'PARSED_OK'
          AND (author.name = 'Invoices' OR publisher.name = 'Acme')
    """)
    assert isinstance(ast.where, And)
    assert isinstance(ast.where.left, BinaryOp)


def test_group_by_having_aggregate_alias():
    ast = parse("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        HAVING COUNT(*) > 10
        ORDER BY total DESC
    """)
    assert len(ast.group_by) == 1
    assert ast.group_by[0].table == "author"
    assert ast.group_by[0].name == "id"
    assert isinstance(ast.having, BinaryOp)
    assert isinstance(ast.having.left, Aggregate)
    assert any(isinstance(expr, Alias) for expr in ast.select.columns)


def test_math_expression():
    ast = parse("SELECT book.* FROM book WHERE book.pages * 2 + 1 > 5")
    assert isinstance(ast.where.left, ArithmeticOp)
    assert ast.where.left.op == "+"
    assert isinstance(ast.where.left.left, ArithmeticOp)
    assert ast.where.left.left.op == "*"


def test_string_functions():
    ast = parse("SELECT book.* FROM book WHERE LOWER(TRIM(book.filename)) = 'invoice-a.pdf'")
    assert isinstance(ast.where.left, FunctionCall)
    assert ast.where.left.name == "lower"
    assert isinstance(ast.where.left.args[0], FunctionCall)
    assert ast.where.left.args[0].name == "trim"


def test_json_path_extract_text():
    ast = parse("SELECT book.* FROM book WHERE book.result->'invoice'->>'currency' = 'EUR'")
    assert isinstance(ast.where.left, JsonPath)
    assert ast.where.left.base.table == "book"
    assert ast.where.left.base.name == "result"
    assert ast.where.left.path == ["invoice", "currency"]
    assert ast.where.left.returns_text


def test_json_array_path():
    ast = parse("SELECT book.* FROM book WHERE book.result->'lines'->0->>'amount' = '100.50'")
    assert isinstance(ast.where.left, JsonPath)
    assert ast.where.left.path == ["lines", 0, "amount"]


def test_cast_json_numeric():
    ast = parse("SELECT book.* FROM book WHERE (book.result->'invoice'->>'total')::numeric > 100")
    assert isinstance(ast.where.left, CastExpr)
    assert isinstance(ast.where.left.expression, JsonPath)


def test_case_when_expression():
    ast = parse("SELECT SUM(CASE WHEN book.status = 'PARSEDOK' THEN 1 ELSE 0 END) AS parsed_ok FROM book")
    alias = ast.select.columns[0]
    assert isinstance(alias.expression, Aggregate)
    assert isinstance(alias.expression.expression, CaseExpr)
    assert len(alias.expression.expression.whens) == 1


def test_distinct_and_plain_selected_columns():
    ast = parse("""
        SELECT DISTINCT book.status, author.name
        FROM book
        JOIN author ON book.author_id = author.id
    """)
    assert ast.distinct
    assert [c.name for c in ast.select.columns] == ["status", "name"]
    assert [c.table for c in ast.select.columns] == ["book", "author"]


def test_in_not_and_is_not_null():
    # sqlglot <= 30.8 represents "x IS NOT NULL" as Not(BinaryOp(IS NULL)); newer
    # versions emit a single BinaryOp(IS NOT NULL). Both are accepted downstream.
    def is_not_null(node):
        if isinstance(node, BinaryOp):
            return node.op == "IS NOT NULL"
        if isinstance(node, Not) and isinstance(node.expr, BinaryOp):
            return node.expr.op == "IS NULL"
        return False

    def is_in(node):
        return isinstance(node, Not) and isinstance(node.expr, BinaryOp) and node.expr.op == "IN"

    ast = parse("""
        SELECT book.*
        FROM book
        WHERE NOT book.status IN ('FAILED')
          AND book.created_at IS NOT NULL
    """)
    assert isinstance(ast.where, And)
    assert is_not_null(ast.where.right)
    assert is_in(ast.where.left)


def test_column_to_column_comparison():
    ast = parse("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE book.publisher_id = author.publisher_id
    """)
    assert isinstance(ast.where, BinaryOp)
    assert isinstance(ast.where.left, Column)
    assert isinstance(ast.where.right, Column)
    assert ast.where.left.name == "publisher_id"
    assert ast.where.right.name == "publisher_id"


def test_select_expression_aliases():
    ast = parse("""
        SELECT LOWER(book.filename) AS normalized_filename,
               book.pages * 2 AS weighted_pages
        FROM book
    """)
    assert len(ast.select.columns) == 2
    assert isinstance(ast.select.columns[0], Alias)
    assert isinstance(ast.select.columns[0].expression, FunctionCall)
    assert ast.select.columns[0].alias == "normalized_filename"
    assert isinstance(ast.select.columns[1].expression, ArithmeticOp)


def test_json_key_operators():
    has_key = parse("SELECT book.* FROM book WHERE book.metadata ? 'source'")
    has_any = parse("SELECT book.* FROM book WHERE book.metadata ?| array['source', 'priority']")
    has_all = parse("SELECT book.* FROM book WHERE book.metadata ?& array['source', 'priority']")
    assert isinstance(has_key.where, JsonHasKey)
    assert isinstance(has_any.where, JsonHasAnyKeys)
    assert isinstance(has_all.where, JsonHasAllKeys)


def test_json_contains_operator():
    ast = parse("""SELECT book.* FROM book WHERE book.metadata @> '{"source": "email"}'""")
    assert isinstance(ast.where, JsonContains)


def test_json_path_inside_function_single():
    # SQLGlot parses col->'key' as Lambda when used as a function argument.
    ast = parse("SELECT jsonb_array_length(result_json->'line_items') FROM book")
    fn = ast.select.columns[0]
    assert isinstance(fn, FunctionCall)
    assert fn.name == "jsonb_array_length"
    arg = fn.args[0]
    assert isinstance(arg, JsonPath)
    assert arg.path == ["line_items"]
    assert not arg.returns_text


def test_json_path_inside_function_chained():
    ast = parse("SELECT jsonb_array_length(result_json->'a'->'b') FROM book")
    arg = ast.select.columns[0].args[0]
    assert isinstance(arg, JsonPath)
    assert arg.path == ["a", "b"]


def test_json_path_inside_aggregate():
    ast = parse("SELECT SUM(jsonb_array_length(result_json->'lines')) FROM book")
    agg = ast.select.columns[0]
    assert isinstance(agg, Aggregate)
    fn = agg.expression
    assert isinstance(fn, FunctionCall)
    assert fn.args[0].path == ["lines"]


@pytest.mark.parametrize(
    ("expected_name", "sql_expr"),
    [
        ("upper", "UPPER(book.filename)"),
        ("ltrim", "LTRIM(book.filename)"),
        ("rtrim", "RTRIM(book.filename)"),
        ("length", "LENGTH(book.filename)"),
        ("substring", "SUBSTRING(book.filename FROM 1 FOR 7)"),
        ("concat", "CONCAT(book.filename, book.status)"),
        ("coalesce", "COALESCE(book.filename, 'fallback')"),
        ("replace", "REPLACE(book.filename, 'invoice', 'doc')"),
        ("strpos", "STRPOS(book.filename, 'pdf')"),
    ],
)
def test_complete_string_function_surface(expected_name, sql_expr):
    ast = parse(f"SELECT book.* FROM book WHERE {sql_expr} IS NOT NULL")
    expr = ast.where.expr.left if hasattr(ast.where, "expr") else ast.where.left
    assert isinstance(expr, FunctionCall)
    assert expr.name == expected_name


def test_children_never_returns_none():
    ast = parse("""
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
            assert child is not None, f"{node.__class__.__name__}.children() returned None"
            walk(child)

    walk(ast)


def test_lateral_join_requires_exactly_one_of_fn_call_or_subquery():
    with pytest.raises(ValueError):
        LateralJoin(fn_call=None, subquery=None)
    with pytest.raises(ValueError):
        LateralJoin(fn_call=FunctionCall(name="jsonb_array_elements"), subquery=Query())
