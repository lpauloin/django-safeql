from dataclasses import dataclass, field
from typing import Any


def children_of(*nodes):
    return [c for c in nodes if c is not None]


@dataclass
class Node:
    annotations: dict = field(default_factory=dict, init=False)

    def children(self):
        return []


class Expr(Node):
    pass


@dataclass
class Select(Node):
    columns: list[Expr] = field(default_factory=list)

    def children(self):
        return list(self.columns)


@dataclass
class From(Node):
    table: str = ""
    alias: str | None = None


@dataclass
class Join(Node):
    table: str = ""
    alias: str | None = None
    on: Expr | None = None

    def children(self):
        return children_of(self.on)


@dataclass
class OrderBy(Node):
    expression: Expr | None = None
    desc: bool = False

    def children(self):
        return children_of(self.expression)


@dataclass
class Query(Node):
    select: Select | None = None
    from_: From | None = None
    joins: list[Join] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderBy] = field(default_factory=list)
    limit: int | None = None
    distinct: bool = False

    def children(self):
        return children_of(
            self.select,
            self.from_,
            *self.joins,
            self.where,
            *self.group_by,
            self.having,
            *self.order_by,
        )


@dataclass
class Column(Expr):
    table: str | None = None
    name: str = ""


@dataclass
class Literal(Expr):
    value: Any = None


@dataclass
class NullLiteral(Expr):
    pass


@dataclass
class BooleanLiteral(Expr):
    value: bool = False


@dataclass
class ArrayLiteral(Expr):
    values: list[Expr] = field(default_factory=list)

    def children(self):
        return list(self.values)


@dataclass
class BinaryExpr(Expr):
    left: Expr | None = None
    right: Expr | None = None

    def children(self):
        return children_of(self.left, self.right)


@dataclass
class BinaryOp(BinaryExpr):
    op: str = ""


@dataclass
class ArithmeticOp(BinaryExpr):
    op: str = ""


@dataclass
class FunctionCall(Expr):
    name: str = ""
    args: list[Expr] = field(default_factory=list)

    def children(self):
        return list(self.args)


@dataclass
class CaseExpr(Expr):
    whens: list[tuple[Expr, Expr]] = field(default_factory=list)
    default: Expr | None = None

    def children(self):
        result = [c for pair in self.whens for c in pair]
        return result + children_of(self.default)


@dataclass
class And(BinaryExpr):
    pass


@dataclass
class Or(BinaryExpr):
    pass


@dataclass
class Not(Expr):
    expr: Expr | None = None

    def children(self):
        return children_of(self.expr)


@dataclass
class JsonPath(Expr):
    base: Column | None = None
    path: list[str | int] = field(default_factory=list)
    returns_text: bool = True

    def children(self):
        return children_of(self.base)


@dataclass
class JsonContains(Expr):
    left: Expr | None = None
    value: Expr | None = None

    def children(self):
        return children_of(self.left, self.value)


@dataclass
class JsonHasKey(Expr):
    left: Expr | None = None
    key: Expr | None = None

    def children(self):
        return children_of(self.left, self.key)


@dataclass
class JsonHasAnyKeys(Expr):
    left: Expr | None = None
    keys: Expr | None = None

    def children(self):
        return children_of(self.left, self.keys)


@dataclass
class JsonHasAllKeys(Expr):
    left: Expr | None = None
    keys: Expr | None = None

    def children(self):
        return children_of(self.left, self.keys)


@dataclass
class CastExpr(Expr):
    expression: Expr | None = None
    target_type: str = ""

    def children(self):
        return children_of(self.expression)


@dataclass
class Alias(Expr):
    expression: Expr | None = None
    alias: str = ""

    def children(self):
        return children_of(self.expression)


@dataclass
class Aggregate(Expr):
    function: str = ""
    expression: Expr | None = None
    distinct: bool = False
    alias: str | None = None
    extra_args: list = field(default_factory=list)  # e.g. separator for string_agg, value for json_object_agg
    order_by: list = field(default_factory=list)  # ORDER BY inside the aggregate

    def children(self):
        result = children_of(self.expression)
        result.extend(self.extra_args)
        result.extend(self.order_by)
        return result


@dataclass
class LateralJoin(Node):
    """
    LATERAL JOIN — either a set-returning function call or a correlated subquery.
    join_type: "cross" (CROSS/INNER JOIN) or "left" (LEFT JOIN).
    Exactly one of fn_call or subquery must be set.
    """

    fn_call: "FunctionCall | None" = None
    subquery: "Query | None" = None
    alias: str = ""
    join_type: str = "cross"

    def __post_init__(self):
        if (self.fn_call is None) == (self.subquery is None):
            raise ValueError("LateralJoin requires exactly one of fn_call or subquery")

    def children(self):
        if self.fn_call:
            return [self.fn_call]
        return [self.subquery] if self.subquery is not None else []


@dataclass
class ExistsExpr(Expr):
    """EXISTS (SELECT ...) — boolean expression used in WHERE."""

    subquery: "Query | None" = None

    def children(self):
        return children_of(self.subquery)
