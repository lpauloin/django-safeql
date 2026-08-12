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

SUPPORTED_FUNCTIONS = STRING_FUNCTIONS | DATE_FUNCTIONS | JSON_FUNCTIONS
