"""Foundation helper: normalise a SQL cast target type to a canonical name.

Pure string logic shared by the annotation and codegen layers. It never
raises: an unsupported type yields ``None`` so the annotation layer can record
an error annotation and the validation layer can reject it — keeping rejection
a validation concern rather than an annotation/codegen one.
"""

import re

_CANONICAL_CAST_TYPES = {
    "integer": {"int", "integer", "int4", "serial", "bigint", "int8", "bigserial"},
    "float": {"float", "float4", "float8", "double precision", "real"},
    "boolean": {"bool", "boolean"},
    "date": {"date"},
    "datetime": {
        "timestamp",
        "timestamp without time zone",
        "timestamp with time zone",
        "datetime",
        "timestamptz",
    },
    "string": {"text", "varchar", "character varying", "char", "character"},
    "json": {"json", "jsonb"},
}


def normalize_cast_type(type_name: str) -> str | None:
    """Return the canonical cast type for ``type_name``, or ``None`` if unsupported."""
    value = re.sub(r"\s+", " ", type_name.lower().strip())
    if value.startswith("numeric") or value.startswith("decimal"):
        return "decimal"
    for canonical, aliases in _CANONICAL_CAST_TYPES.items():
        if value in aliases:
            return canonical
    return None
