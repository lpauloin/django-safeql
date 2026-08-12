from django_safeql.constants import (
    SUPPORTED_AGGREGATES,
    SUPPORTED_ARITHMETIC_OPS,
    SUPPORTED_FUNCTIONS,
    SUPPORTED_OPS,
    SUPPORTED_SRF_FUNCTIONS,
)
from django_safeql.codegen import literal_value
from django_safeql.exceptions import ValidationError
from django_safeql.nodes import (
    Aggregate,
    Alias,
    ArithmeticOp,
    BinaryOp,
    CaseExpr,
    ExistsExpr,
    FunctionCall,
    JsonContains,
    JsonHasAllKeys,
    JsonHasAnyKeys,
    JsonHasKey,
    JsonPath,
    LateralJoin,
    Node,
    Query,
    Select,
)
from django_safeql.schemas import SQLTranspilerSchema
from django_safeql.visitor import Visitor

# None = any arity; int = exact; tuple = (min, max) where max=None means unbounded
FUNCTION_ARITY = {
    "lower": 1,
    "upper": 1,
    "trim": 1,
    "ltrim": 1,
    "rtrim": 1,
    "length": 1,
    "substring": (2, 3),
    "substr": (2, 3),
    "concat": (2, None),
    "coalesce": (2, None),
    "replace": 3,
    "strpos": 2,
    "position": 2,
    "now": 0,
    "jsonb_array_length": 1,
    "jsonb_typeof": 1,
    "jsonb_strip_nulls": 1,
    "jsonb_pretty": 1,
    "jsonb_extract_path": (2, None),
    "jsonb_extract_path_text": (2, None),
    "jsonb_path_exists": 2,
    "jsonb_path_query_first": 2,
}


def _check_arity(name, arity, spec):
    if spec is None:
        return
    if isinstance(spec, int):
        if arity != spec:
            raise ValidationError(f"Function {name} expects {spec} argument{'s' if spec != 1 else ''}, got {arity}")
        return
    min_args, max_args = spec
    if arity < min_args:
        raise ValidationError(f"Function {name} expects at least {min_args} arguments, got {arity}")
    if max_args is not None and arity > max_args:
        raise ValidationError(f"Function {name} expects at most {max_args} arguments, got {arity}")


def _select_has_aggregate(select: Select | None) -> bool:
    if not select:
        return False
    for expr in select.columns:
        if isinstance(expr, Aggregate):
            return True
        if isinstance(expr, Alias) and isinstance(expr.expression, Aggregate):
            return True
    return False


def _select_has_non_aggregate(select: Select | None) -> bool:
    if not select:
        return False
    for expr in select.columns:
        if isinstance(expr, Aggregate):
            continue
        if isinstance(expr, Alias) and isinstance(expr.expression, Aggregate):
            continue
        return True
    return False


class ValidationVisitor(Visitor):

    def __init__(self, schema: SQLTranspilerSchema):
        self.schema = schema

    def generic_visit(self, node: Node, *args, **kwargs):
        if node.annotations.get("error"):
            raise ValidationError(node.annotations["error"])
        return super().generic_visit(node, *args, **kwargs)

    def visit_Query(self, node: Query):
        if not node.from_:
            raise ValidationError("Missing FROM clause")
        if node.having and not node.group_by:
            raise ValidationError("HAVING requires GROUP BY")
        if node.limit is not None and self.schema.max_limit is not None and node.limit > self.schema.max_limit:
            raise ValidationError(f"LIMIT exceeds maximum allowed value: {self.schema.max_limit}")
        if not node.group_by and _select_has_aggregate(node.select) and _select_has_non_aggregate(node.select):
            raise ValidationError("Cannot mix aggregate and non-aggregate expressions in SELECT without GROUP BY")
        return self.generic_visit(node)

    def visit_BinaryOp(self, node: BinaryOp):
        if node.op not in SUPPORTED_OPS:
            raise ValidationError(f"Unsupported operator: {node.op}")
        self.visit(node.left)
        self.visit(node.right)
        return node

    def visit_JsonPath(self, node: JsonPath):
        if node.annotations.get("is_lateral_path"):
            return node  # Lateral element paths are not validated against the schema
        if not node.path:
            raise ValidationError("Empty JSON path is not supported")
        return self.generic_visit(node)

    def visit_JsonContains(self, node: JsonContains):
        self.visit(node.left)
        value = literal_value(node.value)
        if not isinstance(value, (dict, list)):
            raise ValidationError("JSON contains @> requires object or array JSON value")
        return node

    def visit_JsonHasKey(self, node: JsonHasKey):
        self.visit(node.left)
        if not isinstance(literal_value(node.key), str):
            raise ValidationError("JSON ? operator requires a string key")
        return node

    def visit_JsonHasAnyKeys(self, node: JsonHasAnyKeys):
        self.visit(node.left)
        keys = literal_value(node.keys)
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValidationError("JSON ?| operator requires an array of string keys")
        return node

    def visit_JsonHasAllKeys(self, node: JsonHasAllKeys):
        self.visit(node.left)
        keys = literal_value(node.keys)
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise ValidationError("JSON ?& operator requires an array of string keys")
        return node

    def visit_Aggregate(self, node: Aggregate):
        if node.function.lower() not in SUPPORTED_AGGREGATES:
            raise ValidationError(f"Unsupported aggregate: {node.function}")
        self.visit(node.expression)
        for arg in node.extra_args:
            self.visit(arg)
        for o in node.order_by:
            self.visit(o)
        return node

    def visit_ArithmeticOp(self, node: ArithmeticOp):
        if node.op not in SUPPORTED_ARITHMETIC_OPS:
            raise ValidationError(f"Unsupported arithmetic operator: {node.op}")
        self.visit(node.left)
        self.visit(node.right)
        return node

    def visit_FunctionCall(self, node: FunctionCall):
        name = node.name.lower()
        if name not in SUPPORTED_FUNCTIONS:
            raise ValidationError(f"Unsupported SQL function: {node.name}")
        _check_arity(name, len(node.args), FUNCTION_ARITY.get(name))
        for arg in node.args:
            self.visit(arg)
        return node

    def visit_CaseExpr(self, node: CaseExpr):
        if not node.whens:
            raise ValidationError("CASE requires at least one WHEN clause")
        for condition, result in node.whens:
            self.visit(condition)
            self.visit(result)
        self.visit(node.default)
        return node

    def visit_LateralJoin(self, node: LateralJoin):
        if node.fn_call:
            fn_name = node.fn_call.name.lower()
            if fn_name not in SUPPORTED_SRF_FUNCTIONS:
                raise ValidationError(
                    f"LATERAL function {node.fn_call.name!r} is not supported. "
                    f"Supported set-returning functions: {', '.join(sorted(SUPPORTED_SRF_FUNCTIONS))}. "
                    "For array counts use jsonb_array_length(), or restructure as a correlated subquery."
                )
            return node
        if node.subquery is None:
            raise ValidationError("LATERAL requires a subquery body")
        if not node.alias:
            raise ValidationError("LATERAL JOIN must have an alias (AS <name>)")
        if node.annotations.get("error"):
            raise ValidationError(node.annotations["error"])
        if node.subquery.annotations.get("error"):
            raise ValidationError(node.subquery.annotations["error"])
        self._validate_subquery_body(node.subquery)
        return node

    def visit_ExistsExpr(self, node: ExistsExpr):
        if node.annotations.get("error"):
            raise ValidationError(node.annotations["error"])
        if node.subquery and node.subquery.annotations.get("error"):
            raise ValidationError(node.subquery.annotations["error"])
        if node.subquery:
            self._validate_subquery_body(node.subquery)
        return node

    def _validate_subquery_body(self, subquery: Query):
        # These clauses are accepted by the parser but never applied by codegen
        # (_build_inner_queryset only ever honours WHERE and ORDER BY) — rejecting
        # them here turns a silently-wrong query into a clear error instead.
        if subquery.joins:
            raise ValidationError("JOIN is not supported inside LATERAL/EXISTS subqueries")
        if subquery.group_by:
            raise ValidationError("GROUP BY is not supported inside LATERAL/EXISTS subqueries")
        if subquery.having:
            raise ValidationError("HAVING is not supported inside LATERAL/EXISTS subqueries")
        if subquery.distinct:
            raise ValidationError("DISTINCT is not supported inside LATERAL/EXISTS subqueries")
        if subquery.limit is not None and subquery.limit != 1:
            raise ValidationError(
                "LATERAL/EXISTS subqueries always return at most one correlated row per outer row; "
                "LIMIT must be omitted or set to 1"
            )
        if subquery.where:
            self.visit(subquery.where)
        if subquery.select:
            for col in subquery.select.columns:
                self.visit(col)
        for order in subquery.order_by:
            self.visit(order)
