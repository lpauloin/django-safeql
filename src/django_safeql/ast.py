import re
from decimal import Decimal

import sqlglot
from sqlglot import exp

from django_safeql.exceptions import UnsupportedSQL
from django_safeql.nodes import (
    Aggregate,
    Alias,
    And,
    ArithmeticOp,
    ArrayLiteral,
    BinaryOp,
    BooleanLiteral,
    CaseExpr,
    CastExpr,
    Column,
    ExistsExpr,
    Expr,
    From,
    FunctionCall,
    Join,
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

BINARY_OPS = {
    exp.EQ: "=",
    exp.NEQ: "!=",
    exp.GT: ">",
    exp.GTE: ">=",
    exp.LT: "<",
    exp.LTE: "<=",
    exp.Like: "LIKE",
    exp.ILike: "ILIKE",
}

ARITHMETIC_OPS = {
    exp.Add: "+",
    exp.Sub: "-",
    exp.Mul: "*",
    exp.Div: "/",
    exp.Mod: "%",
}


class SQLGlotParser:

    def parse(self, sql: str) -> Query:
        tree = sqlglot.parse_one(sql, read="postgres")
        return self.visit(tree)

    def visit(self, node: exp.Expression):
        method = getattr(self, f"visit_{node.__class__.__name__}", self.generic_visit)
        return method(node)

    def generic_visit(self, node: exp.Expression):
        if type(node) in BINARY_OPS:
            return self._binary(node)
        if type(node) in ARITHMETIC_OPS:
            return self._arithmetic(node)
        if isinstance(node, exp.Func):
            return self._function(node)
        raise UnsupportedSQL(f"Unsupported SQLGlot node {node.__class__.__name__}: {node}")

    def visit_Select(self, node: exp.Select) -> Query:
        return Query(
            select=Select(columns=[self.visit(expr) for expr in node.expressions]),
            from_=self._from(node),
            joins=self._joins(node),
            where=self.visit(node.args["where"].this) if node.args.get("where") else None,
            group_by=[self.visit(e) for e in node.args["group"].expressions] if node.args.get("group") else [],
            having=self.visit(node.args["having"].this) if node.args.get("having") else None,
            order_by=[self.visit(o) for o in node.args["order"].expressions] if node.args.get("order") else [],
            limit=self._limit(node.args["limit"]) if node.args.get("limit") else None,
            distinct=bool(node.args.get("distinct")),
        )

    def _from(self, node: exp.Select) -> From:
        from_expr = node.args.get("from") or node.args.get("from_")
        if not from_expr or not isinstance(from_expr.this, exp.Table):
            raise UnsupportedSQL("Only simple FROM table is supported")
        table = from_expr.this
        return From(table=table.name, alias=self._alias(table))

    def _joins(self, node: exp.Select) -> list:
        joins = []
        for join in node.args.get("joins") or []:
            side = join.args.get("side")
            side_str = (str(side) if side is not None else "").upper()
            join_type = "left" if "LEFT" in side_str else "cross"
            inner = join.this
            if isinstance(inner, exp.Lateral):
                joins.append(self._lateral_join(inner, join_type=join_type))
            elif isinstance(inner, exp.Table):
                joins.append(
                    Join(
                        table=inner.name,
                        alias=self._alias(inner),
                        on=self.visit(join.args["on"]) if join.args.get("on") else None,
                    )
                )
            else:
                raise UnsupportedSQL(f"Unsupported JOIN expression: {inner.__class__.__name__}: {inner}")
        return joins

    def _lateral_join(self, node: exp.Lateral, join_type: str = "cross") -> LateralJoin:
        alias_node = node.args.get("alias")
        alias = alias_node.name if alias_node else ""
        inner = node.this
        if isinstance(inner, exp.Subquery):
            return LateralJoin(subquery=self.visit(inner.this), alias=alias, join_type=join_type)
        if isinstance(inner, exp.Select):
            return LateralJoin(subquery=self.visit(inner), alias=alias, join_type=join_type)
        fn_call = self.visit(inner)
        if not isinstance(fn_call, FunctionCall):
            raise UnsupportedSQL(f"LATERAL requires a function call or subquery, got: {inner.__class__.__name__}")
        return LateralJoin(fn_call=fn_call, alias=alias, join_type=join_type)

    def _alias(self, table: exp.Table) -> str | None:
        alias = table.args.get("alias")
        return alias.this.name if alias and alias.this else None

    def _limit(self, node: exp.Limit) -> int:
        value = self.visit(node.expression)
        if not isinstance(value, Literal) or not isinstance(value.value, int):
            raise UnsupportedSQL("LIMIT must be an integer literal")
        return value.value

    def visit_Star(self, node: exp.Star) -> Column:
        return Column(name="*")

    def visit_Column(self, node: exp.Column) -> Column:
        return Column(table=node.table or None, name=node.name)

    def visit_Identifier(self, node: exp.Identifier) -> Column:
        return Column(name=node.name)

    def visit_Literal(self, node: exp.Literal) -> Literal:
        if node.is_string:
            return Literal(node.this)
        text = node.this
        if re.fullmatch(r"-?\d+", text):
            return Literal(int(text))
        if re.fullmatch(r"-?\d+\.\d+", text):
            return Literal(Decimal(text))
        return Literal(text)

    def visit_Null(self, node: exp.Null) -> NullLiteral:
        return NullLiteral()

    def visit_Boolean(self, node: exp.Boolean) -> BooleanLiteral:
        return BooleanLiteral(bool(node.this))

    def visit_Array(self, node: exp.Array) -> ArrayLiteral:
        return ArrayLiteral(values=[self.visit(e) for e in node.expressions])

    def visit_Paren(self, node: exp.Paren):
        return self.visit(node.this)

    def visit_And(self, node: exp.And) -> And:
        return And(left=self.visit(node.left), right=self.visit(node.right))

    def visit_Or(self, node: exp.Or) -> Or:
        return Or(left=self.visit(node.left), right=self.visit(node.right))

    def visit_Not(self, node: exp.Not) -> Not:
        return Not(expr=self.visit(node.this))

    def visit_Exists(self, node: exp.Exists) -> ExistsExpr:
        inner = node.this
        if isinstance(inner, exp.Subquery):
            return ExistsExpr(subquery=self.visit(inner.this))
        if isinstance(inner, exp.Select):
            return ExistsExpr(subquery=self.visit(inner))
        raise UnsupportedSQL("EXISTS requires a subquery")

    def visit_In(self, node: exp.In) -> BinaryOp:
        if isinstance(node.args.get("query"), exp.Subquery):
            raise UnsupportedSQL("Subqueries are not supported")
        return BinaryOp(
            left=self.visit(node.this), op="IN", right=ArrayLiteral([self.visit(e) for e in node.expressions])
        )

    def visit_Is(self, node: exp.Is) -> BinaryOp | Not:
        # sqlglot <= 30.8 parses "x IS NOT NULL" as Not(Is(x, Null())); newer
        # versions parse it as a single Is node with negate=True instead.
        negated = bool(node.args.get("negate"))
        right = self.visit(node.right)
        if isinstance(right, NullLiteral):
            op = "IS NOT NULL" if negated else "IS NULL"
            return BinaryOp(left=self.visit(node.left), op=op, right=right)
        result = BinaryOp(left=self.visit(node.left), op="IS", right=right)
        return Not(expr=result) if negated else result

    def visit_Cast(self, node: exp.Cast) -> CastExpr:
        target = node.to.sql(dialect="postgres").lower() if node.to else ""
        return CastExpr(expression=self.visit(node.this), target_type=target)

    def visit_Case(self, node: exp.Case) -> CaseExpr:
        case_value = self.visit(node.this) if node.this is not None else None
        whens = []
        for condition in node.args.get("ifs") or []:
            when_expr = self.visit(condition.this)
            if case_value is not None:
                when_expr = BinaryOp(left=case_value, op="=", right=when_expr)
            whens.append((when_expr, self.visit(condition.args["true"])))
        default = self.visit(node.args["default"]) if node.args.get("default") is not None else None
        return CaseExpr(whens=whens, default=default)

    def visit_Ordered(self, node: exp.Ordered) -> OrderBy:
        return OrderBy(expression=self.visit(node.this), desc=bool(node.args.get("desc")))

    def visit_Alias(self, node: exp.Alias) -> Alias:
        expression = self.visit(node.this)
        alias = node.alias
        return Alias(expression=expression, alias=alias)

    def visit_Count(self, node: exp.Count) -> Aggregate:
        expression = self.visit(node.this) if node.this else Column(name="*")
        return Aggregate(function="count", expression=expression, distinct=bool(node.args.get("distinct")))

    def visit_Sum(self, node: exp.Sum) -> Aggregate:
        return Aggregate(function="sum", expression=self.visit(node.this), distinct=bool(node.args.get("distinct")))

    def visit_Avg(self, node: exp.Avg) -> Aggregate:
        return Aggregate(function="avg", expression=self.visit(node.this), distinct=bool(node.args.get("distinct")))

    def visit_Min(self, node: exp.Min) -> Aggregate:
        return Aggregate(function="min", expression=self.visit(node.this), distinct=bool(node.args.get("distinct")))

    def visit_Max(self, node: exp.Max) -> Aggregate:
        return Aggregate(function="max", expression=self.visit(node.this), distinct=bool(node.args.get("distinct")))

    def visit_ArrayAgg(self, node: exp.ArrayAgg) -> Aggregate:
        inner = node.this
        distinct = False
        order_by = []
        if isinstance(inner, exp.Distinct):
            distinct = True
            inner = inner.expressions[0]
        elif isinstance(inner, exp.Order):
            order_by = [self.visit(o) for o in inner.expressions]
            inner = inner.this
        return Aggregate(function="array_agg", expression=self.visit(inner), distinct=distinct, order_by=order_by)

    def visit_GroupConcat(self, node) -> Aggregate:
        """STRING_AGG(expr, separator [ORDER BY ...])"""
        inner = node.this
        order_by = []
        if isinstance(inner, exp.Order):
            order_by = [self.visit(o) for o in inner.expressions]
            inner = inner.this
        expression = self.visit(inner)
        sep_node = node.args.get("separator")
        separator = Literal(sep_node.name) if sep_node else Literal(", ")
        return Aggregate(function="string_agg", expression=expression, extra_args=[separator], order_by=order_by)

    def visit_JSONArrayAgg(self, node) -> Aggregate:
        """JSON_AGG(expr)"""
        return Aggregate(function="json_agg", expression=self.visit(node.this))

    def visit_JSONObjectAgg(self, node) -> Aggregate:
        """JSON_OBJECT_AGG(key, value) and JSON_OBJECTAGG(key VALUE value)"""
        exprs = node.expressions
        if exprs and isinstance(exprs[0], exp.JSONKeyValue):
            key = self.visit(exprs[0].this)
            value = self.visit(exprs[0].expression)
        elif len(exprs) >= 2:
            key = self.visit(exprs[0])
            value = self.visit(exprs[1])
        else:
            raise UnsupportedSQL("JSON_OBJECT_AGG requires key and value arguments")
        return Aggregate(function="json_object_agg", expression=key, extra_args=[value])

    def visit_JSONBObjectAgg(self, node) -> Aggregate:
        """JSONB_OBJECT_AGG(key, value)"""
        key = self.visit(node.this)
        value = self.visit(node.args["expression"])
        return Aggregate(function="jsonb_object_agg", expression=key, extra_args=[value])

    def visit_Lower(self, node: exp.Lower) -> FunctionCall:
        return FunctionCall(name="lower", args=[self.visit(node.this)])

    def visit_Upper(self, node: exp.Upper) -> FunctionCall:
        return FunctionCall(name="upper", args=[self.visit(node.this)])

    def visit_Trim(self, node: exp.Trim) -> FunctionCall:
        position = node.args.get("position")
        if position == "LEADING":
            name = "ltrim"
        elif position == "TRAILING":
            name = "rtrim"
        else:
            name = "trim"
        return FunctionCall(name=name, args=[self.visit(node.this)])

    def visit_Length(self, node: exp.Length) -> FunctionCall:
        return FunctionCall(name="length", args=[self.visit(node.this)])

    def visit_Substring(self, node: exp.Substring) -> FunctionCall:
        args = [self.visit(node.this)]
        if node.args.get("start") is not None:
            args.append(self.visit(node.args["start"]))
        if node.args.get("length") is not None:
            args.append(self.visit(node.args["length"]))
        return FunctionCall(name="substring", args=args)

    def visit_Concat(self, node: exp.Concat) -> FunctionCall:
        return FunctionCall(name="concat", args=[self.visit(e) for e in node.expressions])

    def visit_Coalesce(self, node: exp.Coalesce) -> FunctionCall:
        args = []
        if node.this is not None:
            args.append(self.visit(node.this))
        args.extend(self.visit(e) for e in node.expressions)
        return FunctionCall(name="coalesce", args=args)

    def visit_Replace(self, node: exp.Replace) -> FunctionCall:
        return FunctionCall(
            name="replace",
            args=[self.visit(node.this), self.visit(node.expression), self.visit(node.args["replacement"])],
        )

    def visit_StrPosition(self, node: exp.StrPosition) -> FunctionCall:
        return FunctionCall(name="strpos", args=[self.visit(node.this), self.visit(node.args["substr"])])

    def visit_Anonymous(self, node: exp.Anonymous) -> FunctionCall:
        name = node.name.lower()
        # SQLGlot parses some aggregates as Anonymous — route them to Aggregate nodes.
        if name in ("jsonb_agg", "json_arrayagg"):
            canonical = "jsonb_agg" if name == "jsonb_agg" else "json_agg"
            expr = self.visit(node.expressions[0]) if node.expressions else NullLiteral()
            return Aggregate(function=canonical, expression=expr)
        return FunctionCall(name=name, args=[self.visit(e) for e in node.expressions])

    def visit_TimestampTrunc(self, node: exp.TimestampTrunc) -> FunctionCall:
        unit = node.args.get("unit")
        unit_str = unit.name.lower() if unit else "day"
        if unit_str not in {"year", "quarter", "month", "week", "day", "hour"}:
            raise UnsupportedSQL(f"Unsupported date_trunc unit: {unit_str!r}")
        return FunctionCall(name=f"trunc_{unit_str}", args=[self.visit(node.this)])

    def visit_DateTrunc(self, node) -> FunctionCall:
        return self.visit_TimestampTrunc(node)

    def visit_Extract(self, node: exp.Extract) -> FunctionCall:
        # node.this = Var("YEAR"), node.args["expression"] = the datetime column
        field = node.this
        field_str = field.name.lower() if hasattr(field, "name") else str(field).lower()
        if field_str not in {"year", "quarter", "month", "week", "day", "hour", "minute", "second"}:
            raise UnsupportedSQL(f"Unsupported EXTRACT field: {field_str!r}")
        return FunctionCall(name=f"extract_{field_str}", args=[self.visit(node.args["expression"])])

    def visit_CurrentDate(self, node: exp.CurrentDate) -> FunctionCall:
        return FunctionCall(name="now", args=[])

    def visit_CurrentTimestamp(self, node: exp.CurrentTimestamp) -> FunctionCall:
        return FunctionCall(name="now", args=[])

    def visit_Lambda(self, node: exp.Lambda) -> JsonPath:
        # SQLGlot parses col->'key' as Lambda when it appears inside an Anonymous function call.
        # Structure: expressions[0] = base column, this = path (Literal or chained JSONExtract).
        if len(node.expressions) != 1:
            raise UnsupportedSQL(f"Unsupported Lambda expression: {node}")
        base_expr = self.visit(node.expressions[0])
        if isinstance(base_expr, JsonPath):
            base, base_path = base_expr.base, base_expr.path
        elif isinstance(base_expr, Column):
            base, base_path = base_expr, []
        else:
            raise UnsupportedSQL(f"Unsupported Lambda base: {base_expr}")
        path = self._lambda_body_path(node.this)
        return JsonPath(base=base, path=[*base_path, *path], returns_text=False)

    def _lambda_body_path(self, node: exp.Expression) -> list:
        """Collect path parts from a Lambda body (Literal for single step, JSONExtract for chained)."""
        if isinstance(node, exp.JSONExtract):
            return [*self._json_path_parts(node.this), *self._json_path_parts(node.expression)]
        return self._json_path_parts(node)

    def visit_JSONExtract(self, node: exp.JSONExtract) -> JsonPath:
        return self._json_extract(node, returns_text=False)

    def visit_JSONExtractScalar(self, node: exp.JSONExtractScalar) -> JsonPath:
        return self._json_extract(node, returns_text=True)

    def visit_JSONBContains(self, node: exp.Expression) -> JsonHasKey:
        # PostgreSQL: jsonb ? 'key'
        return JsonHasKey(left=self.visit(node.this), key=self.visit(node.expression))

    def visit_ArrayContainsAll(self, node: exp.Expression) -> JsonContains:
        # PostgreSQL: jsonb @> '{...}'
        return JsonContains(left=self.visit(node.this), value=self.visit(node.expression))

    def visit_JSONBContainsAnyTopKeys(self, node: exp.Expression) -> JsonHasAnyKeys:
        # PostgreSQL: jsonb ?| array['a', 'b']
        return JsonHasAnyKeys(left=self.visit(node.this), keys=self.visit(node.expression))

    def visit_JSONBContainsAllTopKeys(self, node: exp.Expression) -> JsonHasAllKeys:
        # PostgreSQL: jsonb ?& array['a', 'b']
        return JsonHasAllKeys(left=self.visit(node.this), keys=self.visit(node.expression))

    def visit_JSONBExists(self, node: exp.Expression) -> JsonHasKey:
        return JsonHasKey(left=self.visit(node.this), key=self.visit(node.expression))

    def visit_JSONBExistsAny(self, node: exp.Expression) -> JsonHasAnyKeys:
        return JsonHasAnyKeys(left=self.visit(node.this), keys=self.visit(node.expression))

    def visit_JSONBExistsAll(self, node: exp.Expression) -> JsonHasAllKeys:
        return JsonHasAllKeys(left=self.visit(node.this), keys=self.visit(node.expression))

    def _json_extract(self, node: exp.Expression, returns_text: bool) -> JsonPath:
        base_expr = self.visit(node.this)
        if isinstance(base_expr, JsonPath):
            base = base_expr.base
            base_path = base_expr.path
        elif isinstance(base_expr, Column):
            base = base_expr
            base_path = []
        else:
            raise UnsupportedSQL(f"Unsupported JSON base expression: {base_expr}")
        path = self._json_path_parts(node.expression)
        return JsonPath(base=base, path=[*base_path, *path], returns_text=returns_text)

    def visit_JSONPath(self, node: exp.JSONPath) -> ArrayLiteral:
        values: list[Expr] = []
        for part in node.expressions:
            if isinstance(part, exp.JSONPathRoot):
                continue
            if isinstance(part, exp.JSONPathKey):
                values.append(Literal(str(part.this)))
                continue
            if isinstance(part, exp.JSONPathSubscript):
                values.append(Literal(int(part.this)))
                continue
            raise UnsupportedSQL(f"Unsupported JSON path component {part.__class__.__name__}: {part}")
        return ArrayLiteral(values=values)

    def _json_path_parts(self, node: exp.Expression) -> list[str | int]:
        parsed = self.visit(node)
        if isinstance(parsed, Literal):
            value = parsed.value
            if isinstance(value, int):
                return [value]
            if isinstance(value, str):
                if value.startswith("{") and value.endswith("}"):
                    return [self._json_path_atom(p) for p in value[1:-1].split(",") if p]
                return [self._json_path_atom(value)]
        if isinstance(parsed, ArrayLiteral):
            return [self._literal_path_atom(v) for v in parsed.values]
        raise UnsupportedSQL(f"Unsupported JSON path: {node}")

    def _json_path_atom(self, value: str) -> str | int:
        value = value.strip().strip("'").strip('"')
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        return value

    def _literal_path_atom(self, node: Expr) -> str | int:
        if not isinstance(node, Literal):
            raise UnsupportedSQL(f"Unsupported JSON path atom: {node}")
        if isinstance(node.value, int):
            return node.value
        if isinstance(node.value, str):
            return self._json_path_atom(node.value)
        raise UnsupportedSQL(f"Unsupported JSON path atom value: {node.value!r}")

    def _binary(self, node: exp.Expression) -> BinaryOp:
        return BinaryOp(
            left=self.visit(node.left),
            op=BINARY_OPS[type(node)],
            right=self.visit(node.right),
        )

    def _arithmetic(self, node: exp.Expression) -> ArithmeticOp:
        return ArithmeticOp(
            left=self.visit(node.left),
            op=ARITHMETIC_OPS[type(node)],
            right=self.visit(node.right),
        )

    def _function(self, node: exp.Func) -> FunctionCall:
        name = node.sql_name().lower()
        args = []
        if node.this is not None:
            args.append(self.visit(node.this))
        args.extend(self.visit(e) for e in node.expressions)
        return FunctionCall(name=name, args=args)
