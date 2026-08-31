from django_safeql import nodes

# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

SUPPORTED_OPS = frozenset(
    [
        "=",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "LIKE",
        "ILIKE",
        "IN",
        "IS NULL",
        "IS NOT NULL",
    ]
)

SUPPORTED_ARITHMETIC_OPS = frozenset(["+", "-", "*", "/", "%"])

# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

# Scalar aggregates — single value output.
SCALAR_AGGREGATES = frozenset(["count", "sum", "avg", "min", "max"])

# Signature + description surfaced in the AI schema context string.
# fmt: off
COLLECTION_AGGREGATE_DESCRIPTIONS = {
    "ARRAY_AGG":        "(expr [DISTINCT] [ORDER BY col [DESC]])   → PostgreSQL array",
    "STRING_AGG":       "(expr, 'sep'     [ORDER BY col [DESC]])   → concatenated text",
    "JSON_AGG":         "(expr)                                    → JSON array",
    "JSONB_AGG":        "(expr)                                    → JSONB array",
    "JSON_OBJECT_AGG":  "(key_expr, val_expr)                      → JSON object",
    "JSONB_OBJECT_AGG": "(key_expr, val_expr)                      → JSONB object",
}
# fmt: on

COLLECTION_AGGREGATES = frozenset(k.lower() for k in COLLECTION_AGGREGATE_DESCRIPTIONS)

SUPPORTED_AGGREGATES = SCALAR_AGGREGATES | COLLECTION_AGGREGATES

# ---------------------------------------------------------------------------
# Functions — string
# ---------------------------------------------------------------------------

STRING_FUNCTIONS = frozenset(
    [
        "lower",
        "upper",
        "trim",
        "ltrim",
        "rtrim",
        "length",
        "substring",
        "substr",  # substr is an alias for substring
        "concat",
        "coalesce",
        "replace",
        "strpos",
        "position",  # position is an alias for strpos
        "left",
        "right",
        "repeat",
        "reverse",
        "lpad",
        "rpad",
    ]
)

# ---------------------------------------------------------------------------
# Functions — math
# ---------------------------------------------------------------------------

MATH_FUNCTIONS = frozenset(
    [
        "abs",
        "ceil",
        "floor",
        "sqrt",
        "sign",
        "exp",
        "ln",
        "round",
        "power",
    ]
)

# ---------------------------------------------------------------------------
# Functions — dates
# ---------------------------------------------------------------------------

# date_trunc('unit', expr) — normalised to trunc_<unit> by the SQL parser.
TRUNC_UNITS = ["year", "quarter", "month", "week", "day", "hour"]

# EXTRACT(part FROM expr) — normalised to extract_<part> by the SQL parser.
EXTRACT_PARTS = TRUNC_UNITS + ["minute", "second"]

TRUNC_FUNCTIONS = frozenset(f"trunc_{u}" for u in TRUNC_UNITS)
EXTRACT_FUNCTIONS = frozenset(f"extract_{p}" for p in EXTRACT_PARTS)

DATE_FUNCTIONS = TRUNC_FUNCTIONS | EXTRACT_FUNCTIONS | {"now"}

# ---------------------------------------------------------------------------
# Functions — JSON (read-only)
# ---------------------------------------------------------------------------

# Signature + description surfaced in the AI schema context string.
# fmt: off
JSON_FUNCTION_DESCRIPTIONS = {
    "jsonb_array_length":      "(expr->'field')             → array item count",
    "jsonb_typeof":            "(expr->'field')             → 'object'|'array'|'string'|'number'|'boolean'|'null'",
    "jsonb_extract_path":      "(expr, 'k1', 'k2', …)       → JSON value at nested path",
    "jsonb_extract_path_text": "(expr, 'k1', 'k2', …)       → text value at nested path",
    "jsonb_strip_nulls":       "(expr)                      → JSON with null fields removed",
    "jsonb_pretty":            "(expr)                      → indented JSON text",
    "jsonb_path_exists":       "(expr, '$.key')             → boolean (use with = TRUE/FALSE in WHERE)",
    "jsonb_path_query_first":  "(expr, '$.items[0]')        → first jsonpath match or NULL",
}
# fmt: on

JSON_FUNCTIONS = frozenset(JSON_FUNCTION_DESCRIPTIONS)

# ---------------------------------------------------------------------------
# Functions — set-returning (LATERAL with jsonb_array_elements etc.)
# ---------------------------------------------------------------------------

# Set-returning functions (SRFs) supported inside LATERAL JOINs.
SUPPORTED_SRF_FUNCTIONS = frozenset({"jsonb_array_elements", "jsonb_array_elements_text"})

# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

SUPPORTED_FUNCTIONS = STRING_FUNCTIONS | MATH_FUNCTIONS | DATE_FUNCTIONS | JSON_FUNCTIONS

# JSON scalar functions that are translated to every backend (so they are not gated;
# the per-target capability keys live on the Feature class in targets.py).
PORTABLE_JSON_FUNCTIONS = frozenset({"jsonb_array_length"})

# ---------------------------------------------------------------------------
# Dialect
# ---------------------------------------------------------------------------


class DialectOp:
    """Keys into a target's `dialect` dict (see targets.py).

    Each key maps to a SQL template with `{expr}` / `{key}` / `{value}` / `{ordering}`
    placeholders that the codegen fills; `%s` markers stay for bound parameters. Keeping
    the SQL text in the per-target dialect means no raw SQL keyword or function name is
    written inline in codegen.
    """

    ILIKE = "ilike"
    STRING_AGG = "string_agg"
    # ARRAY_AGG is emulated as a JSON array on the non-Postgres targets (Postgres keeps its
    # native array via contrib.postgres, so it has no ARRAY_AGG template).
    ARRAY_AGG = "array_agg"
    JSON_AGG = "json_agg"
    JSONB_AGG = "jsonb_agg"
    JSON_OBJECT_AGG = "json_object_agg"
    JSONB_OBJECT_AGG = "jsonb_object_agg"
    JSON_ARRAY_LENGTH = "json_array_length"
    # LATERAL set-returning function → the FROM clause that iterates the array (`{fn}` is
    # the SRF name, `{source}` the array expression), the element reference used in the
    # aggregate, and the cast wrapper (`{expr}`, `{type}`).
    LATERAL_TABLE = "lateral_table"
    LATERAL_ELEMENT = "lateral_element"
    CAST = "cast"


class CastType:
    """Canonical cast target types.

    `normalize_cast_type` maps SQL type names to these; a target's `cast_types` dict maps
    them to the concrete type name emitted in a raw cast (see targets.py). The main cast
    path uses Django's portable `Cast`; only the LATERAL SRF emits raw cast SQL.
    """

    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    STRING = "string"
    JSON = "json"


# LIKE is standard SQL on every backend, so it is not part of the per-target dialect.
SQL_LIKE_TEMPLATE = "({expr}) LIKE %s"

# JSON extract-scalar operator (`->>`), shared by every backend.
SQL_EXTRACT_TEXT_OP = "->>"

# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------

# Every node class the pipeline explicitly handles. Recorded per query during
# annotation and checked fail-closed by validation: a node type nobody planned
# for is rejected instead of slipping through the whitelist unnoticed.
ALLOWED_NODE_TYPES = frozenset(
    {
        nodes.Query,
        nodes.Select,
        nodes.From,
        nodes.Join,
        nodes.OrderBy,
        nodes.Column,
        nodes.Literal,
        nodes.NullLiteral,
        nodes.BooleanLiteral,
        nodes.ArrayLiteral,
        nodes.BinaryOp,
        nodes.ArithmeticOp,
        nodes.FunctionCall,
        nodes.CaseExpr,
        nodes.And,
        nodes.Or,
        nodes.Not,
        nodes.JsonPath,
        nodes.JsonContains,
        nodes.JsonHasKey,
        nodes.JsonHasAnyKeys,
        nodes.JsonHasAllKeys,
        nodes.CastExpr,
        nodes.Alias,
        nodes.Aggregate,
        nodes.LateralJoin,
        nodes.ExistsExpr,
    }
)
