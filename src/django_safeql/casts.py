"""Foundation helper: normalise a SQL cast target type to a canonical name.

Pure string logic shared by the annotation and codegen layers. It never
raises: an unsupported type yields ``None`` so the annotation layer can record
an error annotation and the validation layer can reject it — keeping rejection
a validation concern rather than an annotation/codegen one.

The concrete per-backend type names live on each target (``Target.cast_types``);
this module only turns a written type into a canonical ``CastType`` value.
"""

import re

from django_safeql.constants import CastType

CAST_TYPE_ALIASES = {
    CastType.INTEGER: {"int", "integer", "int4", "serial", "bigint", "int8", "bigserial"},
    CastType.FLOAT: {"float", "float4", "float8", "double precision", "real"},
    CastType.BOOLEAN: {"bool", "boolean"},
    CastType.DATE: {"date"},
    CastType.DATETIME: {
        "timestamp",
        "timestamp without time zone",
        "timestamp with time zone",
        "datetime",
        "timestamptz",
    },
    CastType.STRING: {"text", "varchar", "character varying", "char", "character"},
    CastType.JSON: {"json", "jsonb"},
}


def normalize_cast_type(type_name: str) -> str | None:
    """Return the canonical cast type for ``type_name``, or ``None`` if unsupported."""
    value = re.sub(r"\s+", " ", type_name.lower().strip())
    if value.startswith("numeric") or value.startswith("decimal"):
        return CastType.DECIMAL
    for canonical, aliases in CAST_TYPE_ALIASES.items():
        if value in aliases:
            return canonical
    return None
