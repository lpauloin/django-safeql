from dataclasses import dataclass, field

from django_safeql.constants import CastType, DialectOp


class Vendor:
    """Database vendors, matching Django's connection.vendor."""

    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"
    MYSQL = "mysql"


class Feature:
    """Capability keys a target may or may not support.

    Only features some backend cannot do are listed; anything supported everywhere
    (translated in codegen or portable by construction) is not gated at all. When a
    feature comes to work on every target its key is removed here rather than left as a
    gate that never fires.
    """

    JSON_CONTAINS = "json_contains"  # @> — PostgreSQL and MySQL
    # DISTINCT / inner ORDER BY inside ARRAY_AGG. PostgreSQL (contrib) and SQLite
    # (json_group_array) carry them; MySQL's JSON_ARRAYAGG carries neither.
    ARRAY_AGG_MODIFIERS = "array_agg_modifiers"
    JSONB_SCALAR_FUNCTIONS = "jsonb_scalar_functions"  # jsonb_typeof/extract_path/... — PG only
    JSONPATH = "jsonpath"  # jsonb_path_* — PostgreSQL only
    LATERAL_SRF = "lateral_srf"  # LATERAL set-returning functions — PostgreSQL only


@dataclass(frozen=True)
class Target:
    # `vendor` matches Django's connection.vendor, so a transpiler can check that its
    # declared target agrees with the database the queryset will actually run against.
    # `features` holds the capability keys a target supports; `dialect` the SQL templates
    # that differ between backends; `cast_types` the concrete type name for each canonical
    # CastType in a raw cast (only the LATERAL SRF emits raw casts, so only the
    # LATERAL-capable targets populate it).
    name: str
    vendor: str
    features: frozenset
    dialect: dict = field(default_factory=dict)
    cast_types: dict = field(default_factory=dict)

    def supports(self, feature):
        return feature in self.features


POSTGRESQL = Target(
    name=Vendor.POSTGRESQL,
    vendor=Vendor.POSTGRESQL,
    features=frozenset(
        {
            Feature.JSON_CONTAINS,
            Feature.ARRAY_AGG_MODIFIERS,
            Feature.JSONB_SCALAR_FUNCTIONS,
            Feature.JSONPATH,
            Feature.LATERAL_SRF,
        }
    ),
    dialect={
        DialectOp.ILIKE: "({expr}) ILIKE %s",
        DialectOp.STRING_AGG: "STRING_AGG({expr}, %s{ordering})",
        DialectOp.ARRAY_AGG: "JSON_AGG({distinct}{expr}{ordering})",
        DialectOp.JSON_AGG: "JSON_AGG({expr})",
        DialectOp.JSONB_AGG: "JSONB_AGG({expr})",
        DialectOp.JSON_OBJECT_AGG: "JSON_OBJECT_AGG({key}, {value})",
        DialectOp.JSONB_OBJECT_AGG: "JSONB_OBJECT_AGG({key}, {value})",
        DialectOp.JSON_ARRAY_LENGTH: "JSONB_ARRAY_LENGTH({expr})",
        DialectOp.LATERAL_TABLE: "{fn}({source}) AS elem",
        DialectOp.LATERAL_ELEMENT: "elem",
        DialectOp.CAST: "({expr})::{type}",
    },
    cast_types={
        CastType.INTEGER: "integer",
        CastType.FLOAT: "double precision",
        CastType.DECIMAL: "numeric",
        CastType.BOOLEAN: "boolean",
        CastType.DATE: "date",
        CastType.DATETIME: "timestamp",
        CastType.STRING: "text",
        CastType.JSON: "jsonb",
    },
)

# SQLite and MySQL run the portable/translated subset; they differ from PostgreSQL only
# by the still-Postgres-only features above (plus `@>` on MySQL). ILIKE and the
# STRING/JSON collection aggregates are translated for every backend via the dialect
# templates, so they are not gated by any feature key.
SQLITE = Target(
    name=Vendor.SQLITE,
    vendor=Vendor.SQLITE,
    features=frozenset({Feature.LATERAL_SRF, Feature.ARRAY_AGG_MODIFIERS}),
    dialect={
        DialectOp.ILIKE: "LOWER({expr}) LIKE LOWER(%s)",
        DialectOp.STRING_AGG: "GROUP_CONCAT({expr}, %s)",
        DialectOp.ARRAY_AGG: "json_group_array({distinct}{expr}{ordering})",
        DialectOp.JSON_AGG: "json_group_array({expr})",
        DialectOp.JSONB_AGG: "json_group_array({expr})",
        DialectOp.JSON_OBJECT_AGG: "json_group_object({key}, {value})",
        DialectOp.JSONB_OBJECT_AGG: "json_group_object({key}, {value})",
        DialectOp.JSON_ARRAY_LENGTH: "json_array_length({expr})",
        DialectOp.LATERAL_TABLE: "json_each({source})",
        DialectOp.LATERAL_ELEMENT: "value",
        DialectOp.CAST: "CAST({expr} AS {type})",
    },
    cast_types={
        CastType.INTEGER: "INTEGER",
        CastType.FLOAT: "REAL",
        CastType.DECIMAL: "NUMERIC",
        CastType.BOOLEAN: "INTEGER",
        CastType.DATE: "TEXT",
        CastType.DATETIME: "TEXT",
        CastType.STRING: "TEXT",
        CastType.JSON: "TEXT",
    },
)

# MySQL has no LATERAL SRF (JSON_TABLE needs a literal path, incompatible with binding the
# JSON key as a parameter), so it carries no LATERAL dialect templates.
MYSQL = Target(
    name=Vendor.MYSQL,
    vendor=Vendor.MYSQL,
    features=frozenset({Feature.JSON_CONTAINS}),
    dialect={
        DialectOp.ILIKE: "LOWER({expr}) LIKE LOWER(%s)",
        DialectOp.STRING_AGG: "GROUP_CONCAT({expr} SEPARATOR %s)",
        DialectOp.ARRAY_AGG: "JSON_ARRAYAGG({expr})",
        DialectOp.JSON_AGG: "JSON_ARRAYAGG({expr})",
        DialectOp.JSONB_AGG: "JSON_ARRAYAGG({expr})",
        DialectOp.JSON_OBJECT_AGG: "JSON_OBJECTAGG({key}, {value})",
        DialectOp.JSONB_OBJECT_AGG: "JSON_OBJECTAGG({key}, {value})",
        DialectOp.JSON_ARRAY_LENGTH: "JSON_LENGTH({expr})",
    },
    cast_types={
        CastType.INTEGER: "SIGNED",
        CastType.FLOAT: "DOUBLE",
        CastType.DECIMAL: "DECIMAL",
        CastType.BOOLEAN: "SIGNED",
        CastType.DATE: "DATE",
        CastType.DATETIME: "DATETIME",
        CastType.STRING: "CHAR",
        CastType.JSON: "JSON",
    },
)

TARGETS = {target.name: target for target in (POSTGRESQL, SQLITE, MYSQL)}


def resolve_target(target):
    if isinstance(target, Target):
        return target
    if target in TARGETS:
        return TARGETS[target]
    raise ValueError(f"Unknown target: {target!r}. Choose from {sorted(TARGETS)}.")
