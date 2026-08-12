import re

from django.contrib.postgres.aggregates import ArrayAgg as DjangoArrayAgg
from django.contrib.postgres.aggregates import StringAgg as DjangoStringAgg
from django.db.models import (
    Aggregate as DjangoAggregate,
    Avg,
    BooleanField,
    Case,
    CharField,
    Count,
    DateField,
    DateTimeField,
    DecimalField,
    Exists as DjangoExists,
    F,
    FloatField,
    IntegerField,
    JSONField,
    Max,
    Min,
    OrderBy as DjangoOrderBy,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.expressions import Func
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import (
    Cast,
    Coalesce,
    Concat,
    ExtractDay,
    ExtractHour,
    ExtractMinute,
    ExtractMonth,
    ExtractQuarter,
    ExtractSecond,
    ExtractWeek,
    ExtractYear,
    Length,
    Lower,
    LTrim,
    Now,
    Replace,
    RTrim,
    StrIndex,
    Substr,
    Trim,
    TruncDay,
    TruncHour,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
    Upper,
)

from django_safeql.casts import normalize_cast_type
from django_safeql.literals import literal_value
from django_safeql.nodes import (
    Aggregate,
    Alias,
    And,
    ArithmeticOp,
    BinaryOp,
    BooleanLiteral,
    CaseExpr,
    CastExpr,
    Column,
    ExistsExpr,
    Expr,
    FunctionCall,
    JsonContains,
    JsonHasAllKeys,
    JsonHasAnyKeys,
    JsonHasKey,
    JsonPath,
    LateralJoin,
    Literal,
    Not,
    NullLiteral,
    Or,
    OrderBy,
    Query,
    Select,
)
from django_safeql.visitor import Visitor

OP_TO_LOOKUP = {
    "=": "",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "LIKE": "contains",
    "ILIKE": "icontains",
}


class LikeExpr(Func):
    """Emit a raw LIKE or ILIKE expression, preserving % wildcards exactly as written."""

    def __init__(self, field_expr, pattern, case_insensitive=False, **kwargs):
        self._pattern = pattern
        self._op = "ILIKE" if case_insensitive else "LIKE"
        kwargs.setdefault("output_field", BooleanField())
        super().__init__(field_expr, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return f"({sql}) {self._op} %s", params + [self._pattern]


class JsonbArrayAggFunc(Func):
    """Aggregate over elements of a JSONB array via a correlated scalar subquery.

    Generates: (SELECT AGG((elem->>'key')::cast) FROM fn_name(source) AS elem)
    """

    def __init__(self, source, fn_name, agg_fn, element_key=None, cast_type=None, **kwargs):
        self._fn_name = fn_name
        self._agg_fn = agg_fn.upper()
        self._element_key = element_key
        self._cast_type = cast_type
        super().__init__(source, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        source_sql, params = compiler.compile(self.source_expressions[0])
        cast = f"::{self._cast_type}" if self._cast_type else ""
        extra_params: list = []
        if self._fn_name == "jsonb_array_elements_text":
            val = f"elem{cast}"
        elif self._element_key:
            # element_key comes from the query text (JSON path segment) and must never be
            # interpolated into the SQL string — bind it as a parameter instead.
            val = f"(elem->>%s){cast}"
            extra_params = [self._element_key]
        else:
            val = f"elem{cast}"
        return (
            f"(SELECT {self._agg_fn}({val}) FROM {self._fn_name}({source_sql}) AS elem)",
            extra_params + list(params),
        )


class JsonpathFunc(Func):
    """Func that casts the second argument to ::jsonpath so PostgreSQL accepts text literals."""

    def as_sql(self, compiler, connection, **extra_context):
        sqls, params = [], []
        for i, expr in enumerate(self.source_expressions):
            sql, p = compiler.compile(expr)
            if i == 1:
                sql = f"({sql})::jsonpath"
            sqls.append(sql)
            params.extend(p)
        fn = self.extra.get("function") or self.__class__.function
        return f"{fn}({', '.join(sqls)})", params


class _SafeJSONOutputField(JSONField):
    """JSON output field that handles both str and already-decoded Python values.

    Django's JSONField.from_db_value unconditionally calls json.loads(), but some
    PostgreSQL aggregate functions return Python objects directly via psycopg2.
    """

    def from_db_value(self, value, expression, connection):
        if value is None or isinstance(value, (dict, list, bool, int, float)):
            return value
        return super().from_db_value(value, expression, connection)


class JsonAgg(DjangoAggregate):
    function = "JSON_AGG"
    name = "JsonAgg"

    def __init__(self, expression, **kwargs):
        kwargs.setdefault("output_field", _SafeJSONOutputField())
        super().__init__(expression, **kwargs)


class JsonbAgg(DjangoAggregate):
    function = "JSONB_AGG"
    name = "JsonbAgg"

    def __init__(self, expression, **kwargs):
        kwargs.setdefault("output_field", JSONField())
        super().__init__(expression, **kwargs)


class JsonObjectAgg(DjangoAggregate):
    function = "JSON_OBJECT_AGG"
    name = "JsonObjectAgg"

    def __init__(self, key_expr, value_expr, **kwargs):
        kwargs.setdefault("output_field", _SafeJSONOutputField())
        super().__init__(key_expr, value_expr, **kwargs)


class JsonbObjectAgg(DjangoAggregate):
    function = "JSONB_OBJECT_AGG"
    name = "JsonbObjectAgg"

    def __init__(self, key_expr, value_expr, **kwargs):
        kwargs.setdefault("output_field", JSONField())
        super().__init__(key_expr, value_expr, **kwargs)


AGGREGATE_TO_DJANGO = {
    "count": Count,
    "sum": Sum,
    "avg": Avg,
    "min": Min,
    "max": Max,
}

FUNCTION_TO_DJANGO = {
    "lower": Lower,
    "upper": Upper,
    "trim": Trim,
    "ltrim": LTrim,
    "rtrim": RTrim,
    "length": Length,
    "substring": Substr,
    "substr": Substr,
    "concat": Concat,
    "coalesce": Coalesce,
    "replace": Replace,
    "strpos": StrIndex,
    "position": StrIndex,
    # date_trunc
    "trunc_year": TruncYear,
    "trunc_quarter": TruncQuarter,
    "trunc_month": TruncMonth,
    "trunc_week": TruncWeek,
    "trunc_day": TruncDay,
    "trunc_hour": TruncHour,
    # EXTRACT
    "extract_year": ExtractYear,
    "extract_quarter": ExtractQuarter,
    "extract_month": ExtractMonth,
    "extract_week": ExtractWeek,
    "extract_day": ExtractDay,
    "extract_hour": ExtractHour,
    "extract_minute": ExtractMinute,
    "extract_second": ExtractSecond,
    # CURRENT_DATE / CURRENT_TIMESTAMP → zero-arg lambda
    "now": lambda: Now(),
    # JSON — scalar read-only functions
    "jsonb_array_length": lambda expr: Func(expr, function="JSONB_ARRAY_LENGTH", output_field=IntegerField()),
    "jsonb_typeof": lambda expr: Func(expr, function="JSONB_TYPEOF", output_field=CharField()),
    "jsonb_extract_path": lambda *args: Func(*args, function="JSONB_EXTRACT_PATH", output_field=JSONField()),
    "jsonb_extract_path_text": lambda *args: Func(*args, function="JSONB_EXTRACT_PATH_TEXT", output_field=CharField()),
    "jsonb_strip_nulls": lambda expr: Func(expr, function="JSONB_STRIP_NULLS", output_field=JSONField()),
    "jsonb_pretty": lambda expr: Func(expr, function="JSONB_PRETTY", output_field=CharField()),
    # jsonpath functions — second arg requires ::jsonpath cast
    "jsonb_path_exists": lambda col, path: JsonpathFunc(
        col, path, function="JSONB_PATH_EXISTS", output_field=BooleanField()
    ),
    "jsonb_path_query_first": lambda col, path: JsonpathFunc(
        col, path, function="JSONB_PATH_QUERY_FIRST", output_field=JSONField()
    ),
}

TEXT_FUNCTIONS = frozenset(
    [
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "substring",
        "substr",
        "concat",
        "replace",
        "coalesce",
    ]
)


class StaticRows:
    """Small iterable result used for SQL aggregate() output."""

    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def __getitem__(self, key):
        return self.rows[key]

    def __len__(self):
        return len(self.rows)


class CodegenVisitor(Visitor):

    def __init__(self):
        self.annotate_kwargs: dict = {}
        self.annotation_counter: int = 0
        self.codegen_aliases: dict[str, str] = {}
        self.aggregate_aliases: dict[str, str] = {}
        self.aggregate_signatures: dict[tuple, str] = {}
        self.lateral_fn_sources: dict[str, tuple] = {}

    def next_alias(self, prefix: str) -> str:
        self.annotation_counter += 1
        safe_prefix = re.sub(r"\W+", "_", prefix).strip("_") or "expr"
        return f"_sql_{safe_prefix[:48]}_{self.annotation_counter}"

    def visit_Query(self, node: Query) -> QuerySet:
        if any(isinstance(j, LateralJoin) for j in node.joins):
            return self._visit_lateral_query(node)
        return self._visit_query_in_scope(node)

    def _visit_lateral_query(self, node: Query) -> "QuerySet | StaticRows":
        qs = node.annotations["base_queryset"]
        for join in node.joins:
            if isinstance(join, LateralJoin) and join.fn_call:
                self._register_lateral_fn_call(join)
            elif isinstance(join, LateralJoin) and join.subquery:
                qs = self._annotate_lateral_subquery(qs, join)
        node.annotations["base_queryset"] = qs
        return self._visit_query_in_scope(node)

    def _register_lateral_fn_call(self, join: LateralJoin):
        fn_name = join.annotations.get("fn_name") or join.fn_call.name.lower()
        source_expr = self.expression_for_annotation(join.fn_call.args[0]) if join.fn_call.args else None
        self.lateral_fn_sources[join.alias] = (fn_name, source_expr)

    def _annotate_lateral_subquery(self, qs: "QuerySet", lateral_join: LateralJoin) -> "QuerySet":
        subquery_ast = lateral_join.subquery
        inner_model = lateral_join.annotations.get("inner_model")
        alias = lateral_join.alias

        inner_qs_base = self._build_inner_queryset(subquery_ast, inner_model)

        for selected in subquery_ast.select.columns if subquery_ast.select else []:
            col_node, col_alias = (
                (selected.expression, selected.alias)
                if isinstance(selected, Alias)
                else (selected, getattr(selected, "name", None))
            )

            if col_alias is None:
                continue
            ann_key = f"{alias}_{col_alias}"

            if isinstance(col_node, Aggregate):
                subq = self._build_aggregate_subquery(inner_qs_base, col_node, subquery_ast)
            else:
                inner_field = col_node.annotations.get("django_path", getattr(col_node, "name", col_alias))
                try:
                    output_field = inner_model._meta.get_field(inner_field)
                except Exception:
                    output_field = CharField()
                subq = Subquery(inner_qs_base.values(inner_field)[:1], output_field=output_field)

            qs = qs.annotate(**{ann_key: subq})
            self.codegen_aliases[ann_key] = ann_key

        if lateral_join.join_type == "cross" and subquery_ast.select and subquery_ast.select.columns:
            first = subquery_ast.select.columns[0]
            first_alias = first.alias if isinstance(first, Alias) else getattr(first, "name", None)
            if first_alias:
                qs = qs.filter(**{f"{alias}_{first_alias}__isnull": False})

        return qs

    def _build_aggregate_subquery(self, inner_qs_base: "QuerySet", agg: Aggregate, subquery_ast: Query) -> "Subquery":
        fn = agg.function.lower()
        # Validation guarantees only scalar aggregates reach a LATERAL subquery.
        agg_class = AGGREGATE_TO_DJANGO[fn]

        if isinstance(agg.expression, Column) and agg.expression.name == "*":
            source = "pk"
        else:
            source = agg.expression.annotations.get("django_path", getattr(agg.expression, "name", "pk"))

        corr_field = self._find_correlated_field(subquery_ast.where)
        if corr_field:
            inner_qs = inner_qs_base.order_by().values(corr_field).annotate(_agg=agg_class(source)).values("_agg")
        else:
            inner_qs = inner_qs_base.order_by().annotate(_agg=agg_class(source)).values("_agg")

        if fn == "count":
            output_field = IntegerField()
        elif fn == "avg":
            output_field = FloatField()
        else:
            output_field = DecimalField(max_digits=30, decimal_places=10)

        return Subquery(inner_qs[:1], output_field=output_field)

    def _find_correlated_field(self, where_node) -> "str | None":
        """Find the inner field used in a correlated (OuterRef) equality condition."""
        if where_node is None:
            return None
        if isinstance(where_node, (And, Not)):
            left = getattr(where_node, "left", None) or getattr(where_node, "expr", None)
            right = getattr(where_node, "right", None)
            return self._find_correlated_field(left) or self._find_correlated_field(right)
        if isinstance(where_node, BinaryOp) and where_node.op == "=":
            lft, rgt = where_node.left, where_node.right
            if rgt.annotations.get("is_outer_ref") and isinstance(lft, Column):
                return lft.annotations.get("django_path", lft.name)
            if lft.annotations.get("is_outer_ref") and isinstance(rgt, Column):
                return rgt.annotations.get("django_path", rgt.name)
        return None

    def _build_inner_queryset(self, subquery_ast: Query, inner_model) -> "QuerySet":
        saved = self.annotate_kwargs
        self.annotate_kwargs = {}
        qs = inner_model.objects.all()
        if subquery_ast.where:
            where_q = self.visit(subquery_ast.where)
            qs = self._flush_annotations(qs)
            qs = qs.filter(where_q)
        if subquery_ast.order_by:
            qs = qs.order_by(*[self.visit(o) for o in subquery_ast.order_by])
        self.annotate_kwargs = saved
        return qs

    def _extract_lateral_srf_info(self, expr):
        """Return (fn_name, source_expr, element_key, cast_type) if expr references a lateral SRF alias, else None."""
        cast_type = None
        inner = expr
        if isinstance(inner, CastExpr):
            cast_type = inner.annotations.get("cast_type") or normalize_cast_type(inner.target_type)
            inner = inner.expression
        if isinstance(inner, JsonPath) and inner.annotations.get("is_lateral_path"):
            alias = inner.annotations["lateral_alias"]
            if alias in self.lateral_fn_sources:
                fn_name, source_expr = self.lateral_fn_sources[alias]
                element_key = str(inner.path[0]) if inner.path else None
                return fn_name, source_expr, element_key, cast_type
        if isinstance(inner, Column) and inner.annotations.get("is_lateral_ref"):
            alias = inner.annotations.get("lateral_alias", inner.name)
            if alias in self.lateral_fn_sources:
                fn_name, source_expr = self.lateral_fn_sources[alias]
                return fn_name, source_expr, None, cast_type
        return None

    def _is_lateral_srf_expr(self, expr) -> bool:
        inner = expr
        if isinstance(inner, CastExpr):
            inner = inner.expression
        if isinstance(inner, JsonPath):
            return inner.annotations.get("is_lateral_path", False)
        if isinstance(inner, Column):
            return inner.annotations.get("is_lateral_ref", False) and inner.name in self.lateral_fn_sources
        return False

    def _agg_output_field(self, function: str, cast_type: str | None = None):
        if function == "count":
            return IntegerField()
        if cast_type == "integer":
            return IntegerField()
        if cast_type in ("decimal", "float"):
            return DecimalField(max_digits=30, decimal_places=10)
        if cast_type == "numeric":
            return DecimalField(max_digits=30, decimal_places=10)
        return FloatField()

    def visit_ExistsExpr(self, node: "ExistsExpr") -> "Q":
        subquery = node.subquery
        inner_model = subquery.annotations.get("inner_model")
        inner_qs = self._build_inner_queryset(subquery, inner_model)
        ann_name = self.next_alias("exists")
        self.annotate_kwargs[ann_name] = DjangoExists(inner_qs)
        return Q(**{ann_name: True})

    def _visit_query_in_scope(self, node: Query) -> QuerySet:
        qs = node.annotations["base_queryset"]

        where_q = self.visit(node.where) if node.where else None
        qs = self._flush_annotations(qs)
        if where_q is not None:
            qs = qs.filter(where_q)

        if node.group_by:
            group_fields = self._group_by_value_fields(node)
            group_field_set = set(group_fields)
            # Annotate non-aggregate select expressions that appear in GROUP BY before .values(),
            # so Django can reference them by name in the GROUP BY clause.
            pre_collected: set[str] = set()
            for selected in node.select.columns if node.select else []:
                if (
                    isinstance(selected, Alias)
                    and not isinstance(selected.expression, Aggregate)
                    and selected.alias in group_field_set
                ):
                    self._collect_select_expression(selected)
                    pre_collected.add(selected.alias)
            qs = self._flush_annotations(qs)
            qs = qs.values(*group_fields)
            for selected in node.select.columns if node.select else []:
                if isinstance(selected, Alias) and selected.alias in pre_collected:
                    continue
                self._collect_select_expression(selected)
            qs = self._flush_annotations(qs)
            if node.having:
                having_q = self.visit(node.having)
                qs = self._flush_annotations(qs)
                qs = qs.filter(having_q)
        else:
            if self._select_has_aggregate(node.select):
                return self._aggregate_without_group_by(qs, node)
            else:
                value_fields = self._plain_select_value_fields(node.select)
                qs = self._flush_annotations(qs)
                if value_fields:
                    qs = qs.values(*value_fields)

        if node.distinct:
            qs = qs.distinct()
        if node.order_by:
            qs = qs.order_by(*[self.visit(o) for o in node.order_by])
        if node.limit is not None:
            qs = qs[: node.limit]
        return qs

    def _select_has_aggregate(self, select: Select | None) -> bool:
        if not select:
            return False
        for expr_ in select.columns:
            if isinstance(expr_, Aggregate):
                return True
            if isinstance(expr_, Alias) and isinstance(expr_.expression, Aggregate):
                return True
        return False

    def _aggregate_without_group_by(self, qs: QuerySet, node: Query) -> StaticRows:
        aggregate_kwargs = {}
        srf_pre_annotations = {}

        for selected in node.select.columns if node.select else []:
            aggregate = selected.expression if isinstance(selected, Alias) else selected
            alias = (
                selected.alias
                if isinstance(selected, Alias)
                else aggregate.alias or self.next_alias(aggregate.function)
            )
            agg_expr = self.aggregate_for_queryset(aggregate)
            if isinstance(agg_expr, JsonbArrayAggFunc):
                # Pre-annotate per-row, then wrap outer aggregate over annotation.
                pre_key = f"_srf_{alias}"
                srf_pre_annotations[pre_key] = agg_expr
                outer_agg_class = AGGREGATE_TO_DJANGO.get(aggregate.function.lower(), Sum)
                aggregate_kwargs[alias] = outer_agg_class(pre_key)
            else:
                aggregate_kwargs[alias] = agg_expr

        if srf_pre_annotations:
            qs = qs.annotate(**srf_pre_annotations)
        qs = self._flush_annotations(qs)
        rows = [qs.aggregate(**aggregate_kwargs)]
        if node.limit == 0:
            rows = []
        return StaticRows(rows)

    def _flush_annotations(self, qs: QuerySet) -> QuerySet:
        if self.annotate_kwargs:
            qs = qs.annotate(**self.annotate_kwargs)
            self.annotate_kwargs = {}
        return qs

    def _group_by_value_fields(self, node: Query) -> list[str]:
        # Every GROUP BY expression becomes a .values() field, whether or not it's
        # also selected — SQL doesn't require them to match, and dropping a GROUP BY
        # column just because it isn't selected would silently turn an aggregate
        # query into a per-row one (e.g. "SELECT COUNT(*) ... GROUP BY status" would
        # otherwise group by every column instead of by status).
        group_paths = [self.visit(expr_) for expr_ in node.group_by]
        return list(dict.fromkeys(group_paths))

    def _plain_select_value_fields(self, select: Select | None) -> list[str]:
        if not select:
            return []
        fields: list[str] = []
        for expr_ in select.columns:
            if isinstance(expr_, Column):
                if expr_.name == "*":
                    fields.extend(self._select_all_value_fields(expr_))
                else:
                    fields.append(self.visit_Column(expr_))
            elif isinstance(expr_, Alias):
                alias = expr_.alias
                if isinstance(expr_.expression, Column) and expr_.expression.name != "*":
                    self.annotate_kwargs[alias] = F(self.visit_Column(expr_.expression))
                    fields.append(alias)
                else:
                    self.annotate_kwargs[alias] = self.expression_for_annotation(expr_.expression)
                    fields.append(alias)
                self.codegen_aliases[alias] = alias
        return fields

    def _select_all_value_fields(self, node: Column) -> list[str]:
        table_schema = node.annotations["table_schema"]
        relation = node.annotations.get("relation", "")
        field_names = self._selectable_field_names(table_schema)
        return [f"{relation}__{field}" if relation else field for field in field_names]

    def _selectable_field_names(self, table_schema) -> list[str]:
        allowed_fields = table_schema.allowed_fields
        concrete_fields = [field.attname for field in table_schema.model._meta.concrete_fields]
        if allowed_fields is None:
            return concrete_fields

        concrete_allowed = [field for field in concrete_fields if field in allowed_fields]
        extra_allowed = sorted(allowed_fields - set(concrete_allowed))
        return [*concrete_allowed, *extra_allowed]

    def _collect_select_expression(self, node: Expr):
        if isinstance(node, Alias):
            if isinstance(node.expression, Aggregate):
                self.visit_Aggregate(node.expression, forced_alias=node.alias)
            else:
                self.annotate_kwargs[node.alias] = self.expression_for_annotation(node.expression)
            self.codegen_aliases[node.alias] = node.alias
            return
        if isinstance(node, Aggregate):
            self.visit_Aggregate(node)
            return

    def visit_And(self, node: And) -> Q:
        return self.visit(node.left) & self.visit(node.right)

    def visit_Or(self, node: Or) -> Q:
        return self.visit(node.left) | self.visit(node.right)

    def visit_Not(self, node: Not) -> Q:
        return ~self.visit(node.expr)

    def visit_BinaryOp(self, node: BinaryOp) -> Q:
        if node.op == "IN":
            field = self.visit(node.left)
            return Q(**{f"{field}__in": literal_value(node.right)})
        if node.op == "IS NULL":
            return Q(**{f"{self.visit(node.left)}__isnull": True})
        if node.op == "IS NOT NULL":
            return Q(**{f"{self.visit(node.left)}__isnull": False})
        if node.op in {"LIKE", "ILIKE"}:
            field_expr = self.expression_for_annotation(node.left)
            pattern = literal_value(node.right)
            alias = self.next_alias("like")
            self.annotate_kwargs[alias] = LikeExpr(field_expr, pattern, case_insensitive=(node.op == "ILIKE"))
            return Q(**{alias: True})
        field = self.visit(node.left)
        if node.right.annotations.get("is_outer_ref"):
            value = OuterRef(node.right.annotations["outer_django_path"])
        elif isinstance(node.right, (Column, JsonPath, CastExpr, ArithmeticOp, FunctionCall, Aggregate, Alias)):
            value = self.expression_for_annotation(node.right)
        else:
            value = literal_value(node.right)
        if isinstance(value, str) and value.startswith("__field__:"):
            value = F(value.removeprefix("__field__:"))
        if node.op == "!=":
            return ~Q(**{field: value})
        lookup = OP_TO_LOOKUP[node.op]
        return Q(**{f"{field}__{lookup}" if lookup else field: value})

    def visit_Column(self, node: Column):
        path = node.annotations.get("django_path", node.name)
        if node.annotations.get("select_alias"):
            return self.codegen_aliases.get(path, path)
        return path

    def visit_JsonPath(self, node: JsonPath) -> str:
        return node.annotations["django_path"]

    def visit_Literal(self, node: Literal) -> str:
        return f"__field__:{node.value}"

    def visit_CastExpr(self, node: CastExpr) -> str:
        source = self.expression_for_annotation(node.expression)
        cast_type = node.annotations.get("cast_type") or normalize_cast_type(node.target_type)
        alias = self.next_alias(f"{self._expr_label(source)}_{cast_type}")
        self.annotate_kwargs[alias] = Cast(source, output_field=django_output_field_for_cast(cast_type))
        return alias

    def visit_ArithmeticOp(self, node: ArithmeticOp) -> str:
        expression = self.expression_for_annotation(node)
        alias = self.next_alias(self._expr_label(expression))
        self.annotate_kwargs[alias] = expression
        return alias

    def visit_FunctionCall(self, node: FunctionCall) -> str:
        expression = self.expression_for_annotation(node)
        alias = self.next_alias(f"{node.name}_{self._expr_label(expression)}")
        self.annotate_kwargs[alias] = expression
        return alias

    def visit_Alias(self, node: Alias) -> str:
        if isinstance(node.expression, Aggregate):
            return self.visit_Aggregate(node.expression, forced_alias=node.alias)
        return node.alias

    def visit_Aggregate(self, node: Aggregate, forced_alias: str | None = None) -> str:
        function = node.function.lower()
        source = self.aggregate_source(node)
        aggregate = self.aggregate_for_queryset(node, source=source)
        signature = (function, str(source), bool(node.distinct))

        if forced_alias is None and node.alias is None and signature in self.aggregate_signatures:
            return self.aggregate_signatures[signature]

        alias = forced_alias or node.alias or self.next_alias(function)
        if alias not in self.annotate_kwargs and alias not in self.aggregate_aliases:
            self.annotate_kwargs[alias] = aggregate

        self.aggregate_signatures[signature] = alias
        self.aggregate_aliases[alias] = alias
        self.codegen_aliases[alias] = alias
        return alias

    def aggregate_for_queryset(self, node: Aggregate, source=None):
        function = node.function.lower()

        if function == "array_agg":
            return self._build_array_agg(node, source)
        if function == "string_agg":
            return self._build_string_agg(node, source)
        if function in ("json_agg", "jsonb_agg"):
            return self._build_json_agg(node, source)
        if function in ("json_object_agg", "jsonb_object_agg"):
            return self._build_json_object_agg(node, source)

        aggregate_class = AGGREGATE_TO_DJANGO[function]
        # Lateral SRF aggregate: build a correlated scalar subquery instead of a plain aggregate.
        if not (isinstance(node.expression, Column) and node.expression.name == "*"):
            srf_info = self._extract_lateral_srf_info(node.expression)
            if srf_info is not None:
                fn_name, source_expr, element_key, cast_type = srf_info
                return JsonbArrayAggFunc(
                    source_expr,
                    fn_name,
                    function,
                    element_key=element_key,
                    cast_type=cast_type,
                    output_field=self._agg_output_field(function, cast_type),
                )
        if source is None:
            source = self.aggregate_source(node)
        return aggregate_class(source, distinct=node.distinct)

    def _aggregate_order_by(self, order_by_nodes):
        parts = []
        for o in order_by_nodes:
            expr = self.expression_for_annotation(o.expression)
            parts.append(DjangoOrderBy(expr, descending=o.desc))
        return tuple(parts)

    def _build_array_agg(self, node: Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        ordering = self._aggregate_order_by(node.order_by)
        return DjangoArrayAgg(source, distinct=node.distinct, ordering=ordering)

    def _build_string_agg(self, node: Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        delimiter = literal_value(node.extra_args[0]) if node.extra_args else ", "
        if not isinstance(delimiter, str):
            delimiter = str(delimiter)
        ordering = self._aggregate_order_by(node.order_by)
        return DjangoStringAgg(source, delimiter, ordering=ordering)

    def _build_json_agg(self, node: Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        cls = JsonAgg if node.function.lower() == "json_agg" else JsonbAgg
        return cls(source)

    def _build_json_object_agg(self, node: Aggregate, source=None):
        cls = JsonObjectAgg if node.function.lower() == "json_object_agg" else JsonbObjectAgg
        if source is None:
            source = self.expression_for_annotation(node.expression)
        value = self.expression_for_annotation(node.extra_args[0]) if node.extra_args else Value(None)
        return cls(source, value)

    def aggregate_source(self, node: Aggregate):
        if isinstance(node.expression, Column) and node.expression.name == "*":
            return "pk"
        # Lateral SRF refs are handled by aggregate_for_queryset — return safe placeholder.
        if self._is_lateral_srf_expr(node.expression):
            return "pk"
        return self.expression_for_annotation(node.expression)

    def visit_JsonContains(self, node: JsonContains) -> Q:
        return Q(**{f"{self.visit(node.left)}__contains": literal_value(node.value)})

    def visit_JsonHasKey(self, node: JsonHasKey) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_key": literal_value(node.key)})

    def visit_JsonHasAnyKeys(self, node: JsonHasAnyKeys) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_any_keys": literal_value(node.keys)})

    def visit_JsonHasAllKeys(self, node: JsonHasAllKeys) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_keys": literal_value(node.keys)})

    def visit_OrderBy(self, node: OrderBy) -> str:
        field = self.visit(node.expression)
        return f"-{field}" if node.desc else field

    def expression_for_annotation(self, node: Expr):
        if isinstance(node, Column):
            # Invariant (enforced by validation): a LATERAL SRF reference only
            # reaches codegen inside an aggregate, handled by aggregate_for_queryset.
            if node.annotations.get("is_lateral_ref") and node.name in self.lateral_fn_sources:
                raise RuntimeError(f"Unexpected LATERAL alias {node.name!r} in a non-aggregate expression")
            path = self.visit_Column(node)
            if path == "*":
                return F("pk")
            return F(path)
        if isinstance(node, JsonPath):
            if node.annotations.get("is_lateral_path"):
                raise RuntimeError("Unexpected LATERAL element access in a non-aggregate expression")
            base_path = node.base.annotations["django_path"]
            expr = F(base_path)
            for i, key in enumerate(node.path):
                is_last = i == len(node.path) - 1
                if is_last and node.returns_text:
                    expr = KeyTextTransform(str(key), expr)
                else:
                    expr = KeyTransform(str(key), expr)
            return expr
        if isinstance(node, Literal):
            return Value(node.value)
        if isinstance(node, NullLiteral):
            return Value(None)
        if isinstance(node, BooleanLiteral):
            return Value(node.value)
        if isinstance(node, CastExpr):
            return F(self.visit_CastExpr(node))
        if isinstance(node, ArithmeticOp):
            left = self.expression_for_annotation(node.left)
            right = self.expression_for_annotation(node.right)
            if node.op == "+":
                return left + right
            if node.op == "-":
                return left - right
            if node.op == "*":
                return left * right
            if node.op == "/":
                return left / right
            if node.op == "%":
                return left % right
        if isinstance(node, FunctionCall):
            name = node.name.lower()
            function = FUNCTION_TO_DJANGO[name]
            args = [self.expression_for_annotation(arg) for arg in node.args]
            if name in TEXT_FUNCTIONS:
                return function(*args, output_field=CharField())
            return function(*args)
        if isinstance(node, CaseExpr):
            whens = [
                When(self.visit(condition), then=self.expression_for_annotation(result))
                for condition, result in node.whens
            ]
            kwargs = {}
            if node.default is not None:
                kwargs["default"] = self.expression_for_annotation(node.default)
            return Case(*whens, **kwargs)
        if isinstance(node, Alias):
            return self.expression_for_annotation(node.expression)
        # Internal invariant: expression shapes reaching codegen are constrained
        # by the parser and rejected earlier by validation if unsupported.
        raise RuntimeError(f"Cannot convert expression to Django annotation: {node!r}")

    def _expr_label(self, expression) -> str:
        return re.sub(r"\W+", "_", str(expression)).strip("_")[:64] or "expr"


def django_output_field_for_cast(cast_type):
    if cast_type == "integer":
        return IntegerField()
    if cast_type == "float":
        return FloatField()
    if cast_type == "decimal":
        return DecimalField(max_digits=30, decimal_places=10)
    if cast_type == "boolean":
        return BooleanField()
    if cast_type == "date":
        return DateField()
    if cast_type == "datetime":
        return DateTimeField()
    if cast_type == "string":
        return CharField()
    if cast_type == "json":
        return JSONField()
    # Internal invariant: cast_type has already been normalised and validated.
    raise RuntimeError(f"Unhandled cast type in codegen: {cast_type!r}")
