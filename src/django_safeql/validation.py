from django_safeql.constants import (
    ALLOWED_NODE_TYPES,
    COLLECTION_AGGREGATES,
    SCALAR_AGGREGATES,
    SUPPORTED_AGGREGATES,
    SUPPORTED_ARITHMETIC_OPS,
    SUPPORTED_FUNCTIONS,
    SUPPORTED_OPS,
    SUPPORTED_SRF_FUNCTIONS,
)
from django_safeql.exceptions import ValidationError
from django_safeql.literals import literal_value
from django_safeql.nodes import (
    Aggregate,
    Alias,
    ArithmeticOp,
    BinaryOp,
    CaseExpr,
    CastExpr,
    Column,
    ExistsExpr,
    From,
    FunctionCall,
    Join,
    JsonContains,
    JsonHasAllKeys,
    JsonHasAnyKeys,
    JsonHasKey,
    JsonPath,
    LateralJoin,
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


class ValidationVisitor(Visitor):

    def __init__(self, schema: SQLTranspilerSchema):
        self.schema = schema

    def visit_Query(self, node: Query):
        self._check_node_types(node)
        if not node.from_:
            raise ValidationError("Missing FROM clause")
        if node.having and not node.group_by:
            raise ValidationError("HAVING requires GROUP BY")
        if node.limit is not None and self.schema.max_limit is not None and node.limit > self.schema.max_limit:
            raise ValidationError(f"LIMIT exceeds maximum allowed value: {self.schema.max_limit}")
        # Validate every sub-node first (surfaces field/table/operator errors and
        # resolves column annotations), then enforce the cross-clause rules on top.
        self.generic_visit(node)
        self._check_aggregation(node)
        return node

    def _check_node_types(self, node: Query):
        # Fail-closed: reject any node type the pipeline does not explicitly handle,
        # rather than letting it slip through unvalidated.
        unknown = node.annotations.get("node_types", set()) - ALLOWED_NODE_TYPES
        if unknown:
            name = sorted(cls.__name__ for cls in unknown)[0]
            raise ValidationError(f"Unsupported expression: {name}")

    # -- Schema resolution decisions ---------------------------------------
    #
    # Annotation attaches the resolved facts (table_schema, sql_table, cast_type,
    # json_field_schema, …), leaving them None when it could not resolve. These
    # methods read those facts and decide whether the query is allowed.

    def visit_From(self, node: From):
        if node.annotations.get("table_schema") is None:
            raise ValidationError(f"Unknown table: {node.table}")
        if node.table != self.schema.base_table:
            raise ValidationError(f"FROM must use base table {self.schema.base_table!r}")
        return node

    def visit_Join(self, node: Join):
        if node.annotations.get("table_schema") is None:
            raise ValidationError(f"Unknown table: {node.table}")
        self.visit(node.on)
        return node

    def visit_Column(self, node: Column):
        self._reject_srf_outside_aggregate(node)
        if node.annotations.get("is_outer_ref"):
            if not node.annotations["field_allowed"]:
                raise ValidationError(
                    f"Unknown field: {node.annotations['outer_table_name']}.{node.annotations['outer_field_name']}"
                )
            return node
        if node.annotations.get("is_lateral_ref") or node.annotations.get("select_alias"):
            return node
        if node.annotations.get("table_schema") is None:
            raise ValidationError(f"Unknown table for column: {node.table}")
        if node.name != "*" and not node.annotations["field_allowed"]:
            raise ValidationError(f"Unknown field: {node.annotations['sql_table']}.{node.name}")
        return node

    def visit_CastExpr(self, node: CastExpr):
        if node.annotations.get("cast_type") is None:
            raise ValidationError(f"Unsupported cast type: {node.target_type}")
        self.visit(node.expression)
        return node

    # -- LATERAL set-returning-function usage ------------------------------
    #
    # Elements produced by a LATERAL set-returning function (jsonb_array_elements
    # and friends) may only be consumed inside a scalar aggregate — the codegen
    # compiles them to a correlated aggregate subquery. Annotation records both
    # facts (is_srf_ref/in_aggregate on the element, wraps_srf on the aggregate),
    # so these decisions ride the normal traversal instead of a second walk.

    def _reject_srf_outside_aggregate(self, node):
        if node.annotations.get("is_srf_ref") and not node.annotations.get("in_aggregate"):
            raise ValidationError(
                "LATERAL set-returning function elements may only be used inside an "
                "aggregate function (SUM, COUNT, AVG, MIN, MAX)"
            )

    # -- GROUP BY / aggregation coverage -----------------------------------
    #
    # SQL-standard rule: in an aggregated query (one with a GROUP BY, or with an
    # aggregate anywhere in SELECT), every non-aggregate expression in SELECT,
    # HAVING and ORDER BY must be "covered" by the GROUP BY — it is one of the
    # GROUP BY expressions, or every column leaf it references (outside of an
    # aggregate) appears in the GROUP BY. Anything else is rejected here instead
    # of being silently reinterpreted downstream (dropped column, HAVING folded
    # into WHERE, or the GROUP BY silently widened).

    def _check_aggregation(self, node: Query):
        if not (node.group_by or _select_has_aggregate(node.select)):
            return
        grouped_keys, grouped_leaves = self._grouping_sets(node)

        for item in node.select.columns if node.select else []:
            expr = item.expression if isinstance(item, Alias) else item
            if not self._covered(expr, grouped_keys, grouped_leaves):
                label = self._ungrouped_label(expr, grouped_leaves)
                raise ValidationError(
                    f"Column {label!r} must appear in GROUP BY or be used in an aggregate function"
                    if label
                    else "SELECT expression must appear in GROUP BY or be used in an aggregate function"
                )

        if node.having is not None and not self._covered(node.having, grouped_keys, grouped_leaves):
            raise ValidationError("HAVING may only reference aggregates or GROUP BY expressions")

        for order in node.order_by:
            if not self._covered(order.expression, grouped_keys, grouped_leaves):
                raise ValidationError(
                    "ORDER BY may only reference aggregates or GROUP BY expressions in an aggregated query"
                )

    def _grouping_sets(self, node: Query):
        grouped_keys: set = set()
        grouped_leaves: set = set()
        for group_expr in node.group_by:
            key = group_expr.annotations["expr_key"]
            grouped_keys.add(key)
            # A group key that is a plain column reference makes that column covered
            # wherever it appears; grouping by an expression does not (only exact
            # matches of the expression are covered, via grouped_keys).
            if key[0] == "col":
                grouped_leaves.add(key)
        return grouped_keys, grouped_leaves

    def _covered(self, expr, grouped_keys: set, grouped_leaves: set) -> bool:
        if expr.annotations["expr_key"] in grouped_keys:
            return True
        return all(leaf in grouped_leaves for leaf in expr.annotations["column_leaves"])

    def _ungrouped_label(self, expr, grouped_leaves: set):
        for leaf in expr.annotations["column_leaves"]:
            if leaf not in grouped_leaves:
                return leaf[1] if len(leaf) == 2 else ".".join(p for p in leaf[1:] if p)
        return None

    def visit_BinaryOp(self, node: BinaryOp):
        if node.op not in SUPPORTED_OPS:
            raise ValidationError(f"Unsupported operator: {node.op}")
        self.visit(node.left)
        self.visit(node.right)
        return node

    def visit_JsonPath(self, node: JsonPath):
        self.visit(node.base)
        self._reject_srf_outside_aggregate(node)
        if node.annotations.get("is_lateral_path"):
            return node  # Lateral element paths are not validated against the schema
        if node.annotations.get("json_base_is_outer_ref"):
            raise ValidationError(
                "JSON path access on a reference to the outer query's table is not "
                "supported inside LATERAL/EXISTS subqueries"
            )
        if not node.path:
            raise ValidationError("Empty JSON path is not supported")
        if "json_field_schema" not in node.annotations:
            return node  # base did not resolve to a table column; visit(base) reported it
        json_field_schema = node.annotations["json_field_schema"]
        if json_field_schema is None:
            raise ValidationError(f"Field is not declared as JSON: {node.base.name}")
        if (
            node.annotations.get("json_path_schema") is None
            and json_field_schema.strict
            and not json_field_schema.allow_unknown_paths
        ):
            raise ValidationError(f"Unknown JSON path: {node.base.name}.{'.'.join(map(str, node.path))}")
        return node

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
        if node.annotations.get("wraps_srf") and node.function.lower() in COLLECTION_AGGREGATES:
            raise ValidationError(
                f"{node.function.upper()} is not supported over LATERAL set-returning functions; "
                "use SUM, COUNT, AVG, MIN or MAX instead"
            )
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
        self._check_subquery_inner_table(node.subquery)
        self._validate_subquery_body(node.subquery)
        return node

    def visit_ExistsExpr(self, node: ExistsExpr):
        if node.subquery:
            self._check_subquery_inner_table(node.subquery)
            self._validate_subquery_body(node.subquery)
        return node

    def _check_subquery_inner_table(self, subquery: Query):
        if subquery.annotations.get("inner_table_schema") is None:
            raise ValidationError(
                f"Unknown table in LATERAL subquery: {subquery.annotations.get('inner_table_name')!r}"
            )

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
                agg = col.expression if isinstance(col, Alias) else col
                if isinstance(agg, Aggregate) and agg.function.lower() not in SCALAR_AGGREGATES:
                    raise ValidationError(
                        f"Aggregate '{agg.function.upper()}' is not supported inside LATERAL/EXISTS subqueries"
                    )
                self.visit(col)
        for order in subquery.order_by:
            self.visit(order)
