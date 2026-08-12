import pytest

from django_safeql.exceptions import ValidationError
from django_safeql.json_schema import JsonSchemaResolver
from django_safeql.nodes import JsonHasAllKeys, JsonHasAnyKeys, JsonHasKey, JsonPath


def test_json_path_schema(transpiler):
    ast = transpiler.to_ast("SELECT book.* FROM book WHERE book.details->'summary'->>'total' = '120.50'")
    json_path = ast.where.left
    assert isinstance(json_path, JsonPath)
    assert json_path.annotations["django_path"] == "details__summary__total"
    assert json_path.annotations["json_type"] == "number"
    assert json_path.annotations["json_schema"]["description"] == "Total amount"


def test_json_array_path_schema(transpiler):
    ast = transpiler.to_ast("SELECT book.* FROM book WHERE book.details->'chapters'->0->>'amount' = '100.50'")
    json_path = ast.where.left
    assert json_path.annotations["django_path"] == "details__chapters__0__amount"
    assert json_path.annotations["json_type"] == "number"


def test_casted_json_numeric_path(transpiler):
    ast = transpiler.to_ast("SELECT book.* FROM book WHERE (book.details->'summary'->>'total')::numeric > 100")
    cast_node = ast.where.left
    assert cast_node.annotations["cast_type"] == "decimal"
    assert cast_node.expression.annotations["django_path"] == "details__summary__total"
    assert cast_node.expression.annotations["json_type"] == "number"


def test_rejects_unknown_json_path(transpiler):
    with pytest.raises(ValidationError, match="Unknown JSON path"):
        transpiler.to_ast("SELECT book.* FROM book WHERE book.details->'summary'->>'missing' = 'x'")


@pytest.mark.parametrize(
    ("where_sql", "expected_type"),
    [
        ("book.metadata ? 'source'", JsonHasKey),
        ("book.metadata ?| array['source', 'priority']", JsonHasAnyKeys),
        ("book.metadata ?& array['source', 'priority']", JsonHasAllKeys),
    ],
)
def test_json_has_key_operators(transpiler, where_sql, expected_type):
    ast = transpiler.to_ast(f"SELECT book.* FROM book WHERE {where_sql}")
    assert isinstance(ast.where, expected_type)
    assert ast.where.left.annotations["django_path"] == "metadata"
    assert ast.where.left.annotations["is_json_field"]


def test_allof_json_schema_resolves_path():
    resolver = JsonSchemaResolver()
    schema = {
        "allOf": [
            {"type": "object", "properties": {"amount": {"type": "number"}}},
            {"type": "object", "properties": {"label": {"type": "string"}}},
        ]
    }
    assert resolver.resolve_path(schema, ["amount"]) == {"type": "number"}
    assert resolver.resolve_path(schema, ["label"]) == {"type": "string"}
    assert resolver.resolve_path(schema, ["missing"]) is None
