from django_safeql.codegen import normalize_cast_type
from django_safeql.json_schema import json_schema_type, JsonSchemaResolver
from django_safeql.nodes import (
    Aggregate,
    Alias,
    ArithmeticOp,
    CaseExpr,
    CastExpr,
    Column,
    ExistsExpr,
    From,
    FunctionCall,
    Join,
    JsonPath,
    LateralJoin,
    Query,
)
from django_safeql.schemas import SQLTranspilerSchema, TableSchema
from django_safeql.scope import ScopeStack
from django_safeql.visitor import Visitor


class AnnotationVisitor(Visitor):
    def __init__(self, schema: SQLTranspilerSchema):
        self.schema = schema
        self.scope = ScopeStack()
        self.json_resolver = JsonSchemaResolver()

    def visit_Query(self, node: Query):
        with self.scope.scoped(node, alias_to_table={}, select_aliases={}, lateral_aliases={}):
            self.visit(node.from_)
            for join in node.joins:
                self.visit(join)
            self.visit(node.select)
            self.visit(node.where)
            for expression in node.group_by:
                self.visit(expression)
            self.visit(node.having)
            for order in node.order_by:
                self.visit(order)
            node.annotations["base_queryset"] = self.schema.base_queryset
            node.annotations["base_model"] = self.schema.base_model
            node.annotations["select_aliases"] = dict(self.scope.get("select_aliases", {}))
        return node

    def visit_From(self, node: From):
        self._annotate_table_node(node, from_clause=True)
        return node

    def visit_Join(self, node: Join):
        self._annotate_table_node(node, from_clause=False)
        self.visit(node.on)
        return node

    def visit_LateralJoin(self, node: LateralJoin):
        if node.fn_call:
            for arg in node.fn_call.args:
                self.visit(arg)
            node.annotations["fn_name"] = node.fn_call.name.lower()
        elif node.subquery:
            outer_alias_to_table = dict(self.scope.get("alias_to_table", {}))
            self._visit_lateral_subquery(node.subquery, outer_alias_to_table)
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

    def _visit_lateral_subquery(self, subquery: "Query", outer_alias_to_table: dict):
        """Annotate the inner query of a lateral join, detecting outer references."""
        if not subquery.from_:
            return
        inner_table_name = subquery.from_.table
        inner_alias = subquery.from_.alias or inner_table_name
        inner_table_schema = self.schema.get_table(inner_table_name)
        if inner_table_schema is None:
            subquery.annotations["error"] = f"Unknown table in LATERAL subquery: {inner_table_name!r}"
            return
        subquery.from_.annotations.update(
            {
                "table_schema": inner_table_schema,
                "model": inner_table_schema.model,
                "relation": inner_table_schema.relation,
            }
        )
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
            if subquery.select:
                for col in subquery.select.columns:
                    self.visit(col)
            self.visit(subquery.where)
            for order in subquery.order_by:
                self.visit(order)
            for gb in subquery.group_by:
                self.visit(gb)
        subquery.annotations.update(
            {
                "inner_table_name": inner_table_name,
                "inner_table_schema": inner_table_schema,
                "inner_model": inner_table_schema.model,
                "inner_relation": inner_table_schema.relation,
            }
        )

    def visit_ExistsExpr(self, node: "ExistsExpr"):
        if node.subquery:
            outer_alias_to_table = dict(self.scope.get("alias_to_table", {}))
            self._visit_lateral_subquery(node.subquery, outer_alias_to_table)
            node.annotations.update(node.subquery.annotations)
        return node

    def _annotate_table_node(self, node: From | Join, from_clause: bool):
        table_schema = self.schema.get_table(node.table)
        if table_schema is None:
            node.annotations["error"] = f"Unknown table: {node.table}"
            return
        if from_clause and node.table != self.schema.base_table:
            node.annotations["error"] = f"FROM must use base table {self.schema.base_table!r}"
            return
        node.annotations.update(
            {"table_schema": table_schema, "model": table_schema.model, "relation": table_schema.relation}
        )
        alias_to_table = self.scope.mutate_mapping("alias_to_table")
        alias_to_table[node.table] = node.table
        if node.alias:
            alias_to_table[node.alias] = node.table

    def visit_Alias(self, node: Alias):
        self.visit(node.expression)
        select_aliases = self.scope.mutate_mapping("select_aliases")
        select_aliases[node.alias] = node.expression
        node.annotations["alias"] = node.alias
        return node

    def visit_Column(self, node: Column):
        if node.name == "*":
            sql_table = self._resolve_table(node.table)
            table_schema = self.schema.get_table(sql_table)
            if table_schema is None:
                node.annotations["error"] = f"Unknown table for column: {node.table}"
                return node
            node.annotations.update(
                {
                    "sql_table": sql_table,
                    "table_schema": table_schema,
                    "model": table_schema.model,
                    "relation": table_schema.relation,
                    "django_path": "*",
                }
            )
            return node
        select_aliases = self.scope.get("select_aliases", {})
        if node.table is None and node.name in select_aliases:
            node.annotations["select_alias"] = node.name
            node.annotations["django_path"] = node.name
            return node
        # Outer reference check — when inside a lateral subquery, a column that
        # references an outer table is an OuterRef, not an inner table column.
        if self.scope.get("is_lateral_subquery") and node.table:
            outer_alias_to_table = self.scope.get("outer_alias_to_table", {})
            if node.table in outer_alias_to_table:
                outer_table_name = outer_alias_to_table[node.table]
                outer_table_schema = self.schema.get_table(outer_table_name)
                if outer_table_schema:
                    if not self._field_allowed(outer_table_schema, node.name):
                        node.annotations["error"] = f"Unknown field: {outer_table_name}.{node.name}"
                        return node
                    outer_rel = outer_table_schema.relation
                    outer_django_path = f"{outer_rel}__{node.name}" if outer_rel else node.name
                    node.annotations.update(
                        {
                            "is_outer_ref": True,
                            "outer_django_path": outer_django_path,
                        }
                    )
                    return node
        # Lateral alias references — column names that refer to a LATERAL JOIN alias.
        lateral_aliases = self.scope.get("lateral_aliases", {})
        sql_table_candidate = self._resolve_table(node.table) if node.table else node.name
        if node.table is None and node.name in lateral_aliases:
            node.annotations.update({"is_lateral_ref": True, "lateral_alias": node.name, "django_path": node.name})
            return node
        if node.table is not None and sql_table_candidate in lateral_aliases:
            lateral_join_node = lateral_aliases[sql_table_candidate]
            if lateral_join_node.subquery is not None:
                ann_key = f"{sql_table_candidate}_{node.name}"
                node.annotations.update(
                    {
                        "is_lateral_ref": True,
                        "lateral_alias": sql_table_candidate,
                        "lateral_field": node.name,
                        "django_path": ann_key,
                    }
                )
            else:
                node.annotations.update(
                    {
                        "is_lateral_ref": True,
                        "lateral_alias": sql_table_candidate,
                        "django_path": sql_table_candidate,
                    }
                )
            return node
        sql_table = self._resolve_table(node.table)
        table_schema = self.schema.get_table(sql_table)
        if table_schema is None:
            node.annotations["error"] = f"Unknown table for column: {node.table}"
            return node
        json_field_names = set(table_schema.json_fields.keys())
        if not self._field_allowed(table_schema, node.name):
            node.annotations["error"] = f"Unknown field: {sql_table}.{node.name}"
            return node
        relation = table_schema.relation
        # Inside a lateral subquery, the inner table has no relation prefix.
        if self.scope.get("is_lateral_subquery") and sql_table == self.scope.get("inner_table_name"):
            relation = ""
        node.annotations.update(
            {
                "sql_table": sql_table,
                "table_schema": table_schema,
                "model": table_schema.model,
                "relation": relation,
                "django_path": f"{relation}__{node.name}" if relation else node.name,
                "is_json_field": node.name in json_field_names,
            }
        )
        return node

    def visit_JsonPath(self, node: JsonPath):
        self.visit(node.base)
        if not node.base or node.base.annotations.get("error"):
            return node
        if node.base.annotations.get("is_lateral_ref"):
            # JSON path on a lateral SRF element (e.g., item->>'amount').
            node.annotations.update(
                {
                    "is_lateral_path": True,
                    "lateral_alias": node.base.annotations["lateral_alias"],
                }
            )
            return node
        base_path = node.base.annotations["django_path"]
        table_schema: TableSchema = node.base.annotations["table_schema"]
        json_field_schema = table_schema.json_fields.get(node.base.name)
        if json_field_schema is None:
            node.annotations["error"] = f"Field is not declared as JSON: {node.base.name}"
            return node
        path_schema = self.json_resolver.resolve_path(json_field_schema.schema, node.path)
        if path_schema is None and json_field_schema.strict and not json_field_schema.allow_unknown_paths:
            node.annotations["error"] = f"Unknown JSON path: {node.base.name}.{'.'.join(map(str, node.path))}"
            return node
        node.annotations.update(
            {
                "django_path": "__".join([base_path, *map(str, node.path)]),
                "json_schema": path_schema,
                "json_type": json_schema_type(path_schema) if path_schema else "unknown",
                "json_format": path_schema.get("format") if path_schema else None,
                "returns_text": node.returns_text,
            }
        )
        return node

    def visit_CastExpr(self, node: CastExpr):
        self.visit(node.expression)
        node.annotations["cast_type"] = normalize_cast_type(node.target_type)
        return node

    def visit_Aggregate(self, node: Aggregate):
        self.visit(node.expression)
        for arg in node.extra_args:
            self.visit(arg)
        for o in node.order_by:
            self.visit(o)
        node.annotations["aggregate_function"] = node.function.lower()
        return node

    def visit_ArithmeticOp(self, node: ArithmeticOp):
        self.visit(node.left)
        self.visit(node.right)
        return node

    def visit_FunctionCall(self, node: FunctionCall):
        for arg in node.args:
            self.visit(arg)
        node.annotations["function_name"] = node.name.lower()
        return node

    def visit_CaseExpr(self, node: CaseExpr):
        for condition, result in node.whens:
            self.visit(condition)
            self.visit(result)
        self.visit(node.default)
        return node

    def _resolve_table(self, table):
        if not table:
            return self.schema.base_table
        return self.scope.get("alias_to_table", {}).get(table, table)

    def _field_allowed(self, table_schema: TableSchema, field_name: str) -> bool:
        """Whether field_name is reachable on table_schema per its whitelist.

        Used both for plain column references and for outer-table references made
        from inside a LATERAL/EXISTS subquery — both must be checked against the
        same whitelist, or the subquery correlation becomes a way to reach fields
        the schema never declared.
        """
        if table_schema.allowed_fields is not None:
            return field_name in table_schema.allowed_fields
        model_field_names = {f.name for f in table_schema.model._meta.get_fields()}
        db_column_names = {getattr(f, "column", None) for f in table_schema.model._meta.fields}
        json_field_names = set(table_schema.json_fields.keys())
        return field_name in model_field_names or field_name in db_column_names or field_name in json_field_names
