"""
django-safeql — a whitelisted SQL-to-QuerySet transpiler for Django.

Parses a restricted subset of PostgreSQL SQL, validates it against a
declarative schema (which tables/columns/functions are allowed), and
compiles it into a real Django ``QuerySet`` — no raw SQL ever reaches
the database. Built for situations where SQL comes from an untrusted
or semi-trusted source (an LLM, an end user, a saved-report feature)
and must be executed safely.
"""

from django_safeql.exceptions import UnsupportedSQL, ValidationError
from django_safeql.schemas import JsonFieldSchema, SQLTranspilerSchema, TableSchema
from django_safeql.transpiler import SQLToQuerySetTranspiler
from django_safeql.utils import pretty_print_sql

__version__ = "2.0.0"

__all__ = [
    "SQLToQuerySetTranspiler",
    "SQLTranspilerSchema",
    "TableSchema",
    "JsonFieldSchema",
    "UnsupportedSQL",
    "ValidationError",
    "pretty_print_sql",
]
