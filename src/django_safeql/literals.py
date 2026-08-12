"""Foundation helper: interpret literal AST nodes as plain Python values.

Shared by the validation and codegen layers (both depend on this module, not
on each other). Kept free of any Django or code-generation concern.
"""

import json

from django_safeql.exceptions import ValidationError
from django_safeql.nodes import ArrayLiteral, BooleanLiteral, Literal, NullLiteral


def literal_value(node):
    if isinstance(node, Literal):
        value = node.value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    return value
        return value
    if isinstance(node, NullLiteral):
        return None
    if isinstance(node, BooleanLiteral):
        return node.value
    if isinstance(node, ArrayLiteral):
        return [literal_value(v) for v in node.values]
    raise ValidationError(f"Expected literal value, got {node}")
