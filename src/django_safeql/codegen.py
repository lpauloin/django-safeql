import re

from django.db.models import (
    Aggregate as DjangoAggregate,
)
from django.db.models import (
    Avg,
    BooleanField,
    Case,
    CharField,
    Count,
    DateField,
    DateTimeField,
    DecimalField,
    F,
    FloatField,
    IntegerField,
    JSONField,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models import (
    Exists as DjangoExists,
)
from django.db.models import (
    OrderBy as DjangoOrderBy,
)
from django.db.models.expressions import Func
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import (
    Abs,
    Cast,
    Ceil,
    Coalesce,
    Concat,
    Exp,
    ExtractDay,
    ExtractHour,
    ExtractMinute,
    ExtractMonth,
    ExtractQuarter,
    ExtractSecond,
    ExtractWeek,
    ExtractYear,
    Floor,
    Left,
    Length,
    Ln,
    Lower,
    LPad,
    LTrim,
    Now,
    Power,
    Repeat,
    Replace,
    Reverse,
    Right,
    Round,
    RPad,
    RTrim,
    Sign,
    Sqrt,
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

from django_safeql import nodes
from django_safeql.casts import normalize_cast_type
from django_safeql.constants import SQL_EXTRACT_TEXT_OP, SQL_LIKE_TEMPLATE, CastType, DialectOp
from django_safeql.literals import literal_value
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
    """Emit a LIKE/ILIKE match from a per-target `{expr}` template, preserving % wildcards.

    The template comes from the target dialect (ILIKE) or the shared LIKE template, so the
    Postgres `ILIKE` keyword and the sqlite/mysql `LOWER() LIKE LOWER()` rewrite are just
    different templates rather than branches here.
    """

    def __init__(self, field_expr, pattern, template, **kwargs):
        self._pattern = pattern
        self._template = template
        kwargs.setdefault("output_field", BooleanField())
        super().__init__(field_expr, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return self._template.format(expr=sql), list(params) + [self._pattern]


class JsonbArrayAggFunc(Func):
    """Aggregate over the elements of a JSON array via a correlated scalar subquery.

    The array-iteration table (`jsonb_array_elements` / `json_each`), the element
    reference (`elem` / `value`) and the cast wrapper all come from the target dialect,
    so the same shape covers PostgreSQL and SQLite.
    """

    def __init__(self, source, fn_name, agg_fn, dialect, cast_types, element_key=None, cast_type=None, **kwargs):
        self._fn_name = fn_name
        self._agg_fn = agg_fn.upper()
        self._element_key = element_key
        self._cast_type = cast_type
        self._dialect = dialect
        self._cast_types = cast_types
        super().__init__(source, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        source_sql, params = compiler.compile(self.source_expressions[0])
        element = self._dialect[DialectOp.LATERAL_ELEMENT]
        extra_params: list = []
        if self._element_key and self._fn_name != "jsonb_array_elements_text":
            # element_key comes from the query text (JSON path segment) and must never be
            # interpolated into the SQL string — bind it as a parameter instead.
            value = f"{element}{SQL_EXTRACT_TEXT_OP}%s"
            extra_params = [self._element_key]
        else:
            value = element
        if self._cast_type:
            value = self._dialect[DialectOp.CAST].format(expr=value, type=self._cast_types[self._cast_type])
        table = self._dialect[DialectOp.LATERAL_TABLE].format(fn=self._fn_name, source=source_sql)
        return (f"(SELECT {self._agg_fn}({value}) FROM {table})", extra_params + list(params))


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


class JsonArrayLength(Func):
    """Number of elements in a JSON array; the function name comes from the target dialect."""

    def __init__(self, expression, template, **kwargs):
        self._template = template
        kwargs.setdefault("output_field", IntegerField())
        super().__init__(expression, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        return self._template.format(expr=sql), params


class SafeJSONOutputField(JSONField):
    """JSON output field that handles both str and already-decoded Python values.

    Django's JSONField.from_db_value unconditionally calls json.loads(), but some
    PostgreSQL aggregate functions return Python objects directly via psycopg2.
    """

    def from_db_value(self, value, expression, connection):
        if value is None or isinstance(value, (dict, list, bool, int, float)):
            return value
        return super().from_db_value(value, expression, connection)


# Collection aggregates. One class per operation, each rendering the SQL template the
# builder read from the target's dialect — so there is no per-backend branching and no
# raw SQL string in the codegen. PostgreSQL is not special: it is just another template.


def render_inner_ordering(ordering, compiler):
    """Compile an aggregate's inner ORDER BY to `" ORDER BY ..."` SQL plus its params.

    The ordering expressions are stored unresolved, so resolve each against the query
    (turning its F() references into real column references) before compiling.
    """
    if not ordering:
        return "", []
    parts, params = [], []
    for order in ordering:
        sql, order_params = compiler.compile(order.resolve_expression(compiler.query))
        parts.append(sql)
        params.extend(order_params)
    return " ORDER BY " + ", ".join(parts), params


class StringAggregate(DjangoAggregate):
    name = "StringAggregate"

    def __init__(self, expression, delimiter, template, ordering=(), **kwargs):
        self._delimiter = delimiter
        self._template = template
        self._ordering = ordering
        kwargs.setdefault("output_field", CharField())
        super().__init__(expression, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        order_sql, order_params = render_inner_ordering(self._ordering, compiler)
        rendered = self._template.format(expr=sql, ordering=order_sql)
        return rendered, list(params) + [self._delimiter] + order_params


class JsonArrayAggregate(DjangoAggregate):
    name = "JsonArrayAggregate"

    def __init__(self, expression, template, distinct=False, ordering=(), **kwargs):
        self._template = template
        self._distinct = distinct
        self._ordering = ordering
        kwargs.setdefault("output_field", SafeJSONOutputField())
        super().__init__(expression, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        sql, params = compiler.compile(self.source_expressions[0])
        distinct = "DISTINCT " if self._distinct else ""
        order_sql, order_params = render_inner_ordering(self._ordering, compiler)
        rendered = self._template.format(expr=sql, distinct=distinct, ordering=order_sql)
        return rendered, list(params) + order_params


class JsonObjectAggregate(DjangoAggregate):
    name = "JsonObjectAggregate"

    def __init__(self, key_expr, value_expr, template, **kwargs):
        self._template = template
        kwargs.setdefault("output_field", SafeJSONOutputField())
        super().__init__(key_expr, value_expr, **kwargs)

    def as_sql(self, compiler, connection, **extra_context):
        key_sql, key_params = compiler.compile(self.source_expressions[0])
        value_sql, value_params = compiler.compile(self.source_expressions[1])
        return self._template.format(key=key_sql, value=value_sql), list(key_params) + list(value_params)


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
    "left": Left,
    "right": Right,
    "repeat": Repeat,
    "reverse": Reverse,
    "lpad": LPad,
    "rpad": RPad,
    # math
    "abs": Abs,
    "ceil": Ceil,
    "floor": Floor,
    "sqrt": Sqrt,
    "sign": Sign,
    "exp": Exp,
    "ln": Ln,
    "round": Round,
    "power": Power,
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
    def __init__(self, target):
        self.target = target
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

    def visit_Query(self, node: nodes.Query) -> QuerySet:
        if any(isinstance(j, nodes.LateralJoin) for j in node.joins):
            return self._visit_lateral_query(node)
        return self._visit_query_in_scope(node)

    def _visit_lateral_query(self, node: nodes.Query) -> "QuerySet | StaticRows":
        qs = node.annotations["base_queryset"]
        for join in node.joins:
            if isinstance(join, nodes.LateralJoin) and join.fn_call:
                self._register_lateral_fn_call(join)
            elif isinstance(join, nodes.LateralJoin) and join.subquery:
                qs = self._annotate_lateral_subquery(qs, join)
        node.annotations["base_queryset"] = qs
        return self._visit_query_in_scope(node)

    def _register_lateral_fn_call(self, join: nodes.LateralJoin):
        fn_name = join.annotations.get("fn_name") or join.fn_call.name.lower()
        source_expr = self.expression_for_annotation(join.fn_call.args[0]) if join.fn_call.args else None
        self.lateral_fn_sources[join.alias] = (fn_name, source_expr)

    def _annotate_lateral_subquery(self, qs: "QuerySet", lateral_join: nodes.LateralJoin) -> "QuerySet":
        subquery_ast = lateral_join.subquery
        inner_model = lateral_join.annotations.get("inner_model")
        alias = lateral_join.alias

        inner_qs_base = self._build_inner_queryset(subquery_ast, inner_model)

        for selected in subquery_ast.select.columns if subquery_ast.select else []:
            col_node, col_alias = (
                (selected.expression, selected.alias)
                if isinstance(selected, nodes.Alias)
                else (selected, getattr(selected, "name", None))
            )

            if col_alias is None:
                continue
            ann_key = f"{alias}_{col_alias}"

            if isinstance(col_node, nodes.Aggregate):
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
            first_alias = first.alias if isinstance(first, nodes.Alias) else getattr(first, "name", None)
            if first_alias:
                qs = qs.filter(**{f"{alias}_{first_alias}__isnull": False})

        return qs

    def _build_aggregate_subquery(
        self, inner_qs_base: "QuerySet", agg: nodes.Aggregate, subquery_ast: nodes.Query
    ) -> "Subquery":
        fn = agg.function.lower()
        # Validation guarantees only scalar aggregates reach a LATERAL subquery.
        agg_class = AGGREGATE_TO_DJANGO[fn]

        if isinstance(agg.expression, nodes.Column) and agg.expression.name == "*":
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
        if isinstance(where_node, (nodes.And, nodes.Not)):
            left = getattr(where_node, "left", None) or getattr(where_node, "expr", None)
            right = getattr(where_node, "right", None)
            return self._find_correlated_field(left) or self._find_correlated_field(right)
        if isinstance(where_node, nodes.BinaryOp) and where_node.op == "=":
            lft, rgt = where_node.left, where_node.right
            if rgt.annotations.get("is_outer_ref") and isinstance(lft, nodes.Column):
                return lft.annotations.get("django_path", lft.name)
            if lft.annotations.get("is_outer_ref") and isinstance(rgt, nodes.Column):
                return rgt.annotations.get("django_path", rgt.name)
        return None

    def _build_inner_queryset(self, subquery_ast: nodes.Query, inner_model) -> "QuerySet":
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
        if isinstance(inner, nodes.CastExpr):
            cast_type = inner.annotations.get("cast_type") or normalize_cast_type(inner.target_type)
            inner = inner.expression
        if isinstance(inner, nodes.JsonPath) and inner.annotations.get("is_lateral_path"):
            alias = inner.annotations["lateral_alias"]
            if alias in self.lateral_fn_sources:
                fn_name, source_expr = self.lateral_fn_sources[alias]
                element_key = str(inner.path[0]) if inner.path else None
                return fn_name, source_expr, element_key, cast_type
        if isinstance(inner, nodes.Column) and inner.annotations.get("is_lateral_ref"):
            alias = inner.annotations.get("lateral_alias", inner.name)
            if alias in self.lateral_fn_sources:
                fn_name, source_expr = self.lateral_fn_sources[alias]
                return fn_name, source_expr, None, cast_type
        return None

    def _is_lateral_srf_expr(self, expr) -> bool:
        inner = expr.expression if isinstance(expr, nodes.CastExpr) else expr
        return bool(inner is not None and inner.annotations.get("is_srf_ref"))

    def _agg_output_field(self, function: str, cast_type: str | None = None):
        if function == "count":
            return IntegerField()
        if cast_type == CastType.INTEGER:
            return IntegerField()
        if cast_type in (CastType.DECIMAL, CastType.FLOAT):
            return DecimalField(max_digits=30, decimal_places=10)
        return FloatField()

    def visit_ExistsExpr(self, node: nodes.ExistsExpr) -> "Q":
        subquery = node.subquery
        inner_model = subquery.annotations.get("inner_model")
        inner_qs = self._build_inner_queryset(subquery, inner_model)
        ann_name = self.next_alias("exists")
        self.annotate_kwargs[ann_name] = DjangoExists(inner_qs)
        return Q(**{ann_name: True})

    def _visit_query_in_scope(self, node: nodes.Query) -> QuerySet:
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
                    isinstance(selected, nodes.Alias)
                    and not isinstance(selected.expression, nodes.Aggregate)
                    and selected.alias in group_field_set
                ):
                    self._collect_select_expression(selected)
                    pre_collected.add(selected.alias)
            qs = self._flush_annotations(qs)
            qs = qs.values(*group_fields)
            for selected in node.select.columns if node.select else []:
                if isinstance(selected, nodes.Alias) and selected.alias in pre_collected:
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

    def _select_has_aggregate(self, select: nodes.Select | None) -> bool:
        if not select:
            return False
        for expr_ in select.columns:
            if isinstance(expr_, nodes.Aggregate):
                return True
            if isinstance(expr_, nodes.Alias) and isinstance(expr_.expression, nodes.Aggregate):
                return True
        return False

    def _aggregate_without_group_by(self, qs: QuerySet, node: nodes.Query) -> StaticRows:
        aggregate_kwargs = {}
        srf_pre_annotations = {}

        for selected in node.select.columns if node.select else []:
            aggregate = selected.expression if isinstance(selected, nodes.Alias) else selected
            alias = (
                selected.alias
                if isinstance(selected, nodes.Alias)
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

    def _group_by_value_fields(self, node: nodes.Query) -> list[str]:
        # Every GROUP BY expression becomes a .values() field, whether or not it's
        # also selected — SQL doesn't require them to match, and dropping a GROUP BY
        # column just because it isn't selected would silently turn an aggregate
        # query into a per-row one (e.g. "SELECT COUNT(*) ... GROUP BY status" would
        # otherwise group by every column instead of by status).
        group_paths = [self.visit(expr_) for expr_ in node.group_by]
        return list(dict.fromkeys(group_paths))

    def _plain_select_value_fields(self, select: nodes.Select | None) -> list[str]:
        if not select:
            return []
        fields: list[str] = []
        for expr_ in select.columns:
            if isinstance(expr_, nodes.Column):
                if expr_.name == "*":
                    fields.extend(self._select_all_value_fields(expr_))
                else:
                    fields.append(self.visit_Column(expr_))
            elif isinstance(expr_, nodes.Alias):
                alias = expr_.alias
                if isinstance(expr_.expression, nodes.Column) and expr_.expression.name != "*":
                    self.annotate_kwargs[alias] = F(self.visit_Column(expr_.expression))
                    fields.append(alias)
                else:
                    self.annotate_kwargs[alias] = self.expression_for_annotation(expr_.expression)
                    fields.append(alias)
                self.codegen_aliases[alias] = alias
        return fields

    def _select_all_value_fields(self, node: nodes.Column) -> list[str]:
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

    def _collect_select_expression(self, node: nodes.Expr):
        if isinstance(node, nodes.Alias):
            if isinstance(node.expression, nodes.Aggregate):
                self.visit_Aggregate(node.expression, forced_alias=node.alias)
            else:
                self.annotate_kwargs[node.alias] = self.expression_for_annotation(node.expression)
            self.codegen_aliases[node.alias] = node.alias
            return
        if isinstance(node, nodes.Aggregate):
            self.visit_Aggregate(node)
            return

    def visit_And(self, node: nodes.And) -> Q:
        return self.visit(node.left) & self.visit(node.right)

    def visit_Or(self, node: nodes.Or) -> Q:
        return self.visit(node.left) | self.visit(node.right)

    def visit_Not(self, node: nodes.Not) -> Q:
        return ~self.visit(node.expr)

    def visit_BinaryOp(self, node: nodes.BinaryOp) -> Q:
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
            template = self.target.dialect[DialectOp.ILIKE] if node.op == "ILIKE" else SQL_LIKE_TEMPLATE
            alias = self.next_alias("like")
            self.annotate_kwargs[alias] = LikeExpr(field_expr, pattern, template)
            return Q(**{alias: True})
        field = self.visit(node.left)
        if node.right.annotations.get("is_outer_ref"):
            value = OuterRef(node.right.annotations["outer_django_path"])
        elif isinstance(
            node.right,
            (
                nodes.Column,
                nodes.JsonPath,
                nodes.CastExpr,
                nodes.ArithmeticOp,
                nodes.FunctionCall,
                nodes.Aggregate,
                nodes.Alias,
            ),
        ):
            value = self.expression_for_annotation(node.right)
        else:
            value = literal_value(node.right)
        if node.op == "!=":
            return ~Q(**{field: value})
        lookup = OP_TO_LOOKUP[node.op]
        return Q(**{f"{field}__{lookup}" if lookup else field: value})

    def visit_Column(self, node: nodes.Column):
        path = node.annotations.get("django_path", node.name)
        if node.annotations.get("select_alias"):
            return self.codegen_aliases.get(path, path)
        return path

    def visit_JsonPath(self, node: nodes.JsonPath) -> str:
        return node.annotations["django_path"]

    def visit_Literal(self, node: nodes.Literal):
        return Value(node.value)

    def visit_CastExpr(self, node: nodes.CastExpr) -> str:
        source = self.expression_for_annotation(node.expression)
        cast_type = node.annotations.get("cast_type") or normalize_cast_type(node.target_type)
        alias = self.next_alias(f"{self._expr_label(source)}_{cast_type}")
        self.annotate_kwargs[alias] = Cast(source, output_field=django_output_field_for_cast(cast_type))
        return alias

    def visit_ArithmeticOp(self, node: nodes.ArithmeticOp) -> str:
        expression = self.expression_for_annotation(node)
        alias = self.next_alias(self._expr_label(expression))
        self.annotate_kwargs[alias] = expression
        return alias

    def visit_FunctionCall(self, node: nodes.FunctionCall) -> str:
        expression = self.expression_for_annotation(node)
        alias = self.next_alias(f"{node.name}_{self._expr_label(expression)}")
        self.annotate_kwargs[alias] = expression
        return alias

    def visit_Alias(self, node: nodes.Alias) -> str:
        if isinstance(node.expression, nodes.Aggregate):
            return self.visit_Aggregate(node.expression, forced_alias=node.alias)
        return node.alias

    def visit_Aggregate(self, node: nodes.Aggregate, forced_alias: str | None = None) -> str:
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

    def aggregate_for_queryset(self, node: nodes.Aggregate, source=None):
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
        if not (isinstance(node.expression, nodes.Column) and node.expression.name == "*"):
            srf_info = self._extract_lateral_srf_info(node.expression)
            if srf_info is not None:
                fn_name, source_expr, element_key, cast_type = srf_info
                return JsonbArrayAggFunc(
                    source_expr,
                    fn_name,
                    function,
                    self.target.dialect,
                    self.target.cast_types,
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

    def _build_array_agg(self, node: nodes.Aggregate, source=None):
        # No portable native array type, so ARRAY_AGG is emulated as a JSON array on every
        # backend (decoded to a Python list, like psycopg gives for a real Postgres array).
        # Validation rejects DISTINCT/ORDER BY on targets whose JSON aggregate cannot carry
        # them (MySQL), so whatever reaches here is supported by the dialect template.
        if source is None:
            source = self.expression_for_annotation(node.expression)
        ordering = self._aggregate_order_by(node.order_by)
        return JsonArrayAggregate(
            source, self.target.dialect[DialectOp.ARRAY_AGG], distinct=node.distinct, ordering=ordering
        )

    def _build_string_agg(self, node: nodes.Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        delimiter = literal_value(node.extra_args[0]) if node.extra_args else ", "
        if not isinstance(delimiter, str):
            delimiter = str(delimiter)
        ordering = self._aggregate_order_by(node.order_by)
        return StringAggregate(source, delimiter, self.target.dialect[DialectOp.STRING_AGG], ordering=ordering)

    def _build_json_agg(self, node: nodes.Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        op = DialectOp.JSONB_AGG if node.function.lower() == "jsonb_agg" else DialectOp.JSON_AGG
        return JsonArrayAggregate(source, self.target.dialect[op])

    def _build_json_object_agg(self, node: nodes.Aggregate, source=None):
        if source is None:
            source = self.expression_for_annotation(node.expression)
        value = self.expression_for_annotation(node.extra_args[0]) if node.extra_args else Value(None)
        op = DialectOp.JSONB_OBJECT_AGG if node.function.lower() == "jsonb_object_agg" else DialectOp.JSON_OBJECT_AGG
        return JsonObjectAggregate(source, value, self.target.dialect[op])

    def aggregate_source(self, node: nodes.Aggregate):
        if isinstance(node.expression, nodes.Column) and node.expression.name == "*":
            return "pk"
        # Lateral SRF refs are handled by aggregate_for_queryset — return safe placeholder.
        if self._is_lateral_srf_expr(node.expression):
            return "pk"
        return self.expression_for_annotation(node.expression)

    def visit_JsonContains(self, node: nodes.JsonContains) -> Q:
        return Q(**{f"{self.visit(node.left)}__contains": literal_value(node.value)})

    def visit_JsonHasKey(self, node: nodes.JsonHasKey) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_key": literal_value(node.key)})

    def visit_JsonHasAnyKeys(self, node: nodes.JsonHasAnyKeys) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_any_keys": literal_value(node.keys)})

    def visit_JsonHasAllKeys(self, node: nodes.JsonHasAllKeys) -> Q:
        return Q(**{f"{self.visit(node.left)}__has_keys": literal_value(node.keys)})

    def visit_OrderBy(self, node: nodes.OrderBy) -> str:
        field = self.visit(node.expression)
        return f"-{field}" if node.desc else field

    def expression_for_annotation(self, node: nodes.Expr):
        if isinstance(node, nodes.Column):
            # Invariant (enforced by validation): a LATERAL SRF reference only
            # reaches codegen inside an aggregate, handled by aggregate_for_queryset.
            if node.annotations.get("is_lateral_ref") and node.name in self.lateral_fn_sources:
                raise RuntimeError(f"Unexpected LATERAL alias {node.name!r} in a non-aggregate expression")
            path = self.visit_Column(node)
            if path == "*":
                return F("pk")
            return F(path)
        if isinstance(node, nodes.JsonPath):
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
        if isinstance(node, nodes.Literal):
            return Value(node.value)
        if isinstance(node, nodes.NullLiteral):
            return Value(None)
        if isinstance(node, nodes.BooleanLiteral):
            return Value(node.value)
        if isinstance(node, nodes.CastExpr):
            return F(self.visit_CastExpr(node))
        if isinstance(node, nodes.ArithmeticOp):
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
        if isinstance(node, nodes.FunctionCall):
            args = [self.expression_for_annotation(arg) for arg in node.args]
            if node.name.lower() == "jsonb_array_length":
                return JsonArrayLength(args[0], self.target.dialect[DialectOp.JSON_ARRAY_LENGTH])
            return FUNCTION_TO_DJANGO[node.name.lower()](*args)
        if isinstance(node, nodes.CaseExpr):
            whens = [
                When(self.visit(condition), then=self.expression_for_annotation(result))
                for condition, result in node.whens
            ]
            kwargs = {}
            if node.default is not None:
                kwargs["default"] = self.expression_for_annotation(node.default)
            return Case(*whens, **kwargs)
        if isinstance(node, nodes.Alias):
            return self.expression_for_annotation(node.expression)
        # Internal invariant: expression shapes reaching codegen are constrained
        # by the parser and rejected earlier by validation if unsupported.
        raise RuntimeError(f"Cannot convert expression to Django annotation: {node!r}")

    def _expr_label(self, expression) -> str:
        return re.sub(r"\W+", "_", str(expression)).strip("_")[:64] or "expr"


def django_output_field_for_cast(cast_type):
    if cast_type == CastType.INTEGER:
        return IntegerField()
    if cast_type == CastType.FLOAT:
        return FloatField()
    if cast_type == CastType.DECIMAL:
        return DecimalField(max_digits=30, decimal_places=10)
    if cast_type == CastType.BOOLEAN:
        return BooleanField()
    if cast_type == CastType.DATE:
        return DateField()
    if cast_type == CastType.DATETIME:
        return DateTimeField()
    if cast_type == CastType.STRING:
        return CharField()
    if cast_type == CastType.JSON:
        return JSONField()
    # Internal invariant: cast_type has already been normalised and validated.
    raise RuntimeError(f"Unhandled cast type in codegen: {cast_type!r}")
