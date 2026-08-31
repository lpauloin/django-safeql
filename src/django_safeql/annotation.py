from django.core.exceptions import FieldDoesNotExist

from django_safeql import nodes
from django_safeql.casts import normalize_cast_type
from django_safeql.json_schema import JsonSchemaResolver, json_schema_type
from django_safeql.schemas import SQLTranspilerSchema
from django_safeql.scope import ScopeStack
from django_safeql.visitor import Visitor


class AnnotationVisitor(Visitor):
    """Resolve every node against the schema and record the facts a validator needs.

    This layer never decides whether a query is *valid* — it only attaches the
    resolved facts (table schema, django path, normalized cast type, JSON field
    schema, outer/lateral reference info, …). A fact may be ``None`` when it
    could not be resolved; deciding whether that ``None`` is an error is the
    validation layer's job.
    """

    def __init__(self, schema: SQLTranspilerSchema):
        self.schema = schema
        self.scope = ScopeStack()
        self.json_resolver = JsonSchemaResolver()

    def visit(self, node, *args, **kwargs):
        if node is None:
            return None
        # On the way down: announce the node's type to the recording (sub)query
        # scope, so each query knows exactly what it is made of.
        self.scope.announce(type(node))
        result = super().visit(node, *args, **kwargs)
        # On the way back up: now that the children are annotated, record which
        # columns this node references outside an aggregate (for GROUP BY coverage).
        self._record_column_leaves(node)
        return result

    def visit_Query(self, node: nodes.Query):
        with self.scope.scoped(node, alias_to_table={}, select_aliases={}, lateral_aliases={}):
            self.scope.record_types()
            self.visit(node.from_)
            for join in node.joins:
                self.visit(join)
            self.visit(node.select)
            self.visit(node.where)
            for expression in node.group_by:
                self.visit(expression)
            # GROUP BY is resolved before HAVING/ORDER so an alias reference there
            # sees its target already marked as grouped.
            node.annotations["grouped_columns"] = self._mark_grouped(node)
            self.visit(node.having)
            for order in node.order_by:
                self.visit(order)
            node.annotations["base_queryset"] = self.schema.base_queryset
            node.annotations["base_model"] = self.schema.base_model
            node.annotations["select_aliases"] = dict(self.scope.get("select_aliases", {}))
            node.annotations["node_types"] = set(self.scope.types())
        return node

    def visit_From(self, node: nodes.From):
        self._annotate_table_node(node)
        return node

    def visit_Join(self, node: nodes.Join):
        self._annotate_table_node(node)
        self.visit(node.on)
        return node

    def visit_LateralJoin(self, node: nodes.LateralJoin):
        if node.fn_call:
            for arg in node.fn_call.args:
                self.visit(arg)
            node.annotations["fn_name"] = node.fn_call.name.lower()
        elif node.subquery:
            self._visit_lateral_subquery(node.subquery)
            node.annotations.update(
                {
                    "inner_model": node.subquery.annotations.get("inner_model"),
                    "inner_table_schema": node.subquery.annotations.get("inner_table_schema"),
                    "join_type": node.join_type,
                }
            )
        lateral_aliases = self.scope.mutate_mapping("lateral_aliases")
        lateral_aliases[node.alias] = node
        node.annotations["alias"] = node.alias
        return node

    def _visit_lateral_subquery(self, subquery: nodes.Query):
        """Annotate the inner query of a lateral/exists join, detecting outer references."""
        if not subquery.from_:
            return
        outer_alias_to_table = dict(self.scope.get("alias_to_table", {}))
        inner_table_name = subquery.from_.table
        inner_alias = subquery.from_.alias or inner_table_name
        inner_table_schema = self._attach_table(subquery.from_, inner_table_name)
        subquery.annotations["inner_table_name"] = inner_table_name
        subquery.annotations["inner_table_schema"] = inner_table_schema
        if inner_table_schema is None:
            return
        inner_alias_to_table = {inner_table_name: inner_table_name}
        if inner_alias != inner_table_name:
            inner_alias_to_table[inner_alias] = inner_table_name
        with self.scope.scoped(
            subquery,
            alias_to_table=inner_alias_to_table,
            select_aliases={},
            lateral_aliases={},
            is_lateral_subquery=True,
            outer_alias_to_table=outer_alias_to_table,
            inner_table_name=inner_table_name,
        ):
            self.scope.record_types()
            if subquery.select:
                for col in subquery.select.columns:
                    self.visit(col)
            self.visit(subquery.where)
            for order in subquery.order_by:
                self.visit(order)
            for gb in subquery.group_by:
                self.visit(gb)
            subquery.annotations["node_types"] = set(self.scope.types())
        subquery.annotations.update(
            {
                "inner_model": inner_table_schema.model,
                "inner_relation": inner_table_schema.relation,
            }
        )

    def visit_ExistsExpr(self, node: nodes.ExistsExpr):
        if node.subquery:
            self._visit_lateral_subquery(node.subquery)
            node.annotations.update(node.subquery.annotations)
        return node

    def _attach_table(self, node, sql_table):
        """Resolve a table name against the schema and record the shared facts.

        Used for every table reference — FROM, JOIN, and columns — so the
        ``table_schema``/``model``/``relation`` facts are produced in one place.
        """
        table_schema = self.schema.get_table(sql_table)
        node.annotations.update({"sql_table": sql_table, "table_schema": table_schema})
        if table_schema is not None:
            node.annotations.update({"model": table_schema.model, "relation": table_schema.relation})
        return table_schema

    def _annotate_table_node(self, node: nodes.From | nodes.Join):
        self._attach_table(node, node.table)
        alias_to_table = self.scope.mutate_mapping("alias_to_table")
        alias_to_table[node.table] = node.table
        if node.alias:
            alias_to_table[node.alias] = node.table

    def visit_Alias(self, node: nodes.Alias):
        self.visit(node.expression)
        select_aliases = self.scope.mutate_mapping("select_aliases")
        select_aliases[node.alias] = node.expression
        node.annotations["alias"] = node.alias
        # An alias in the main query becomes a queryset annotation; Django rejects
        # one that collides with a real field of the base model. Record it so the
        # validation layer can reject it cleanly instead of leaking a ValueError.
        if not self.scope.get("is_lateral_subquery"):
            node.annotations["alias_conflicts_with_field"] = self._is_model_field(self.schema.base_model, node.alias)
        return node

    def _is_model_field(self, model, name) -> bool:
        try:
            model._meta.get_field(name)
            return True
        except FieldDoesNotExist:
            return False

    def visit_Column(self, node: nodes.Column):
        if node.name == "*":
            self._attach_table(node, self._resolve_table(node.table))
            node.annotations["django_path"] = "*"
        elif not (
            self._annotate_select_alias(node) or self._annotate_outer_ref(node) or self._annotate_lateral_ref(node)
        ):
            self._annotate_plain_column(node)
        return node

    def _annotate_select_alias(self, node) -> bool:
        """An unqualified name that matches a SELECT alias refers to that alias."""
        select_aliases = self.scope.get("select_aliases", {})
        if node.table is None and node.name in select_aliases:
            node.annotations.update({"select_alias": node.name, "django_path": node.name})
            return True
        return False

    def _annotate_outer_ref(self, node) -> bool:
        """Inside a lateral subquery, a column qualified with an outer table is a
        correlation (OuterRef), not an inner-table column."""
        if not (self.scope.get("is_lateral_subquery") and node.table):
            return False
        outer_table_name = self.scope.get("outer_alias_to_table", {}).get(node.table)
        outer_table_schema = self.schema.get_table(outer_table_name) if outer_table_name else None
        if outer_table_schema is None:
            return False
        relation = outer_table_schema.relation
        node.annotations.update(
            {
                "is_outer_ref": True,
                "outer_table_name": outer_table_name,
                "outer_field_name": node.name,
                "outer_django_path": f"{relation}__{node.name}" if relation else node.name,
                "field_allowed": self._field_allowed(outer_table_schema, node.name),
            }
        )
        return True

    def _annotate_lateral_ref(self, node) -> bool:
        """A column whose name (or table qualifier) is a LATERAL JOIN alias."""
        lateral_aliases = self.scope.get("lateral_aliases", {})
        if node.table is None and node.name in lateral_aliases:
            if lateral_aliases[node.name].fn_call is not None:
                self._mark_srf_ref(node, node.name)
            else:
                node.annotations.update({"is_lateral_ref": True, "lateral_alias": node.name, "django_path": node.name})
            return True
        alias = self._resolve_table(node.table) if node.table else node.name
        if node.table is not None and alias in lateral_aliases:
            if lateral_aliases[alias].subquery is not None:
                node.annotations.update(
                    {
                        "is_lateral_ref": True,
                        "lateral_alias": alias,
                        "lateral_field": node.name,
                        "django_path": f"{alias}_{node.name}",
                    }
                )
            else:
                self._mark_srf_ref(node, alias)
            return True
        return False

    def _mark_srf_ref(self, node, alias):
        """A reference to an element of a LATERAL set-returning function."""
        node.annotations.update(
            {
                "is_lateral_ref": True,
                "is_srf_ref": True,
                "in_aggregate": self._in_aggregate(),
                "lateral_alias": alias,
                "django_path": alias,
            }
        )

    def _annotate_plain_column(self, node):
        table_schema = self._attach_table(node, self._resolve_table(node.table))
        if table_schema is None:
            return
        # Inside a lateral subquery, the inner table carries no relation prefix.
        if self.scope.get("is_lateral_subquery") and node.annotations["sql_table"] == self.scope.get(
            "inner_table_name"
        ):
            node.annotations["relation"] = ""
        relation = node.annotations["relation"]
        node.annotations.update(
            {
                "django_path": f"{relation}__{node.name}" if relation else node.name,
                "is_json_field": node.name in table_schema.json_fields,
                "field_allowed": self._field_allowed(table_schema, node.name),
            }
        )

    def visit_JsonPath(self, node: nodes.JsonPath):
        self.visit(node.base)
        base_annotations = node.base.annotations if node.base else {}
        if base_annotations.get("is_lateral_ref"):
            # JSON path on a lateral SRF element (e.g., item->>'amount').
            node.annotations.update(
                {
                    "is_lateral_path": True,
                    "is_srf_ref": True,
                    "in_aggregate": self._in_aggregate(),
                    "lateral_alias": base_annotations["lateral_alias"],
                }
            )
            return node
        if base_annotations.get("is_outer_ref"):
            node.annotations["json_base_is_outer_ref"] = True
            return node
        table_schema = base_annotations.get("table_schema")
        if table_schema is None:
            # Base column did not resolve to a table; validation reports it there.
            return node
        json_field_schema = table_schema.json_fields.get(node.base.name)
        node.annotations["json_field_schema"] = json_field_schema
        if json_field_schema is None:
            return node
        path_schema = self.json_resolver.resolve_path(json_field_schema.schema, node.path)
        base_path = base_annotations["django_path"]
        node.annotations.update(
            {
                "json_path_schema": path_schema,
                "django_path": "__".join([base_path, *map(str, node.path)]),
                "json_schema": path_schema,
                "json_type": json_schema_type(path_schema) if path_schema else "unknown",
                "json_format": path_schema.get("format") if path_schema else None,
                "returns_text": node.returns_text,
            }
        )
        return node

    def visit_CastExpr(self, node: nodes.CastExpr):
        self.visit(node.expression)
        node.annotations["cast_type"] = normalize_cast_type(node.target_type)
        return node

    def visit_Aggregate(self, node: nodes.Aggregate):
        # A scope flag visible to every descendant: it lets a lateral SRF element
        # record whether it is consumed inside an aggregate, without a re-walk.
        with self.scope.scoped(node, in_aggregate=True):
            self.visit(node.expression)
            for arg in node.extra_args:
                self.visit(arg)
            for o in node.order_by:
                self.visit(o)
        node.annotations["aggregate_function"] = node.function.lower()
        node.annotations["wraps_srf"] = self._is_srf_ref(self._unwrap_cast(node.expression))
        return node

    def visit_ArithmeticOp(self, node: nodes.ArithmeticOp):
        self.visit(node.left)
        self.visit(node.right)
        return node

    def visit_FunctionCall(self, node: nodes.FunctionCall):
        for arg in node.args:
            self.visit(arg)
        node.annotations["function_name"] = node.name.lower()
        return node

    def visit_CaseExpr(self, node: nodes.CaseExpr):
        for condition, result in node.whens:
            self.visit(condition)
            self.visit(result)
        self.visit(node.default)
        return node

    def _resolve_table(self, table):
        if not table:
            return self.schema.base_table
        return self.scope.get("alias_to_table", {}).get(table, table)

    def _unwrap_cast(self, expr):
        return expr.expression if isinstance(expr, nodes.CastExpr) else expr

    def _in_aggregate(self):
        return bool(self.scope.get("in_aggregate"))

    # -- GROUP BY coverage facts -------------------------------------------
    #
    # The validation layer needs, per SELECT/HAVING/ORDER expression:
    #   column_leaves — the django paths of the columns it references outside an
    #                   aggregate (recorded bottom-up in _record_column_leaves)
    #   is_grouped    — True when this very expression is one of the GROUP BY
    #                   expressions (marked in _mark_grouped)
    # It then decides coverage against grouped_columns; it never re-derives these.

    def _resolve_alias(self, node):
        """Follow a chain of SELECT-alias references to the underlying expression."""
        select_aliases = self.scope.get("select_aliases", {})
        seen = set()
        while (
            isinstance(node, nodes.Column)
            and node.annotations.get("select_alias") in select_aliases
            and id(node) not in seen
        ):
            seen.add(id(node))
            node = select_aliases[node.annotations["select_alias"]]
        return node

    def _record_column_leaves(self, node):
        if isinstance(node, nodes.Aggregate):
            node.annotations["column_leaves"] = set()  # inner columns need no grouping
        elif isinstance(node, nodes.Column):
            target = self._resolve_alias(node)
            if target is node:
                node.annotations["column_leaves"] = {_column_path(node)}
            else:
                # A reference to a SELECT alias inherits the target's facts.
                node.annotations["column_leaves"] = set(target.annotations.get("column_leaves", set()))
                if target.annotations.get("is_grouped"):
                    node.annotations["is_grouped"] = True
        else:
            leaves = set()
            for child in node.children():
                leaves |= child.annotations.get("column_leaves", set())
            node.annotations["column_leaves"] = leaves

    def _mark_grouped(self, node: nodes.Query):
        """Mark every GROUP BY expression as grouped and return the paths of those
        that are plain columns. A grouped plain column is covered wherever it
        appears; grouping by a larger expression only covers that same expression."""
        grouped_columns = set()
        for expression in node.group_by:
            target = self._resolve_alias(expression)
            target.annotations["is_grouped"] = True
            if isinstance(target, nodes.Column):
                grouped_columns.add(_column_path(target))
        return grouped_columns

    def _is_srf_ref(self, expr) -> bool:
        """Whether ``expr`` resolves to a LATERAL set-returning-function element.

        Single source of truth for SRF detection, consumed by both the validation
        and codegen layers via the ``is_srf_ref`` annotation.
        """
        return bool(expr is not None and expr.annotations.get("is_srf_ref"))

    def _field_allowed(self, table_schema, field_name: str) -> bool:
        """Whether ``field_name`` is reachable on ``table_schema`` per its whitelist.

        Pure schema/model introspection — a fact the validation layer consumes as
        a boolean without needing to know how it was derived.
        """
        if table_schema.allowed_fields is not None:
            return field_name in table_schema.allowed_fields
        model_field_names = {f.name for f in table_schema.model._meta.get_fields()}
        db_column_names = {getattr(f, "column", None) for f in table_schema.model._meta.fields}
        json_field_names = set(table_schema.json_fields.keys())
        return field_name in model_field_names or field_name in db_column_names or field_name in json_field_names


def _column_path(column):
    return column.annotations.get("django_path") or f"{column.table}.{column.name}"
