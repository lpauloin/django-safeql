# django-safeql

A whitelisted SQL-to-QuerySet transpiler for Django.

`django-safeql` parses a restricted subset of PostgreSQL SQL, validates it
against a schema you declare (which tables, columns, functions and operators
are allowed), and compiles it straight into a real Django `QuerySet` — no
raw SQL ever touches the database. It's built for situations where a SQL
query comes from an untrusted or semi-trusted source — an LLM answering
questions over your data, an end-user-facing query box, a saved-report
feature — and has to run safely against your existing Django models.

- **No SQL injection surface** — the input is parsed into an AST and
  compiled to ORM calls; nothing is ever executed as a raw string.
- **Whitelist by construction** — only the tables, columns, operators,
  functions and aggregates you declare in the schema are reachable. Anything
  else is rejected before it gets near the database.
- **Real QuerySets out** — the result is a normal Django `QuerySet`, so it
  composes with everything else in your app (pagination, further
  `.filter()`, `select_related`, etc.).

## Install

```bash
pip install django-safeql
```

Requires Django ≥ 4.2 and a PostgreSQL database (some supported functions —
JSON operators, `ARRAY_AGG`, `STRING_AGG` — are Postgres-specific).

## Quickstart

```python
from django_safeql import SQLTranspilerSchema, TableSchema, JsonFieldSchema, SQLToQuerySetTranspiler
from myapp.models import Book, Author

schema = SQLTranspilerSchema(
    base_table="book",
    base_queryset=Book.objects.all(),
    tables={
        "book": TableSchema(
            queryset=Book.objects.all(),
            relation="",
            allowed_fields={"id", "title", "status", "author_id", "pages", "details"},
            json_fields={
                "details": JsonFieldSchema(schema={
                    "type": "object",
                    "properties": {
                        "language": {"type": "string"},
                        "edition": {"type": "integer"},
                    },
                }),
            },
        ),
        "author": TableSchema(
            queryset=Author.objects.all(),
            relation="author",
            allowed_fields={"id", "name"},
        ),
    },
    max_limit=1000,
)

transpiler = SQLToQuerySetTranspiler(schema)

queryset = transpiler.to_queryset("""
    SELECT book.title, author.name
      FROM book
      JOIN author ON book.author_id = author.id
     WHERE book.status = 'published'
       AND book.details->>'language' = 'en'
     ORDER BY book.pages DESC
     LIMIT 20
""")

list(queryset)  # a normal QuerySet — evaluate it however you like
```

Anything outside the declared schema is rejected before touching the
database:

```python
transpiler.to_queryset("SELECT * FROM pg_catalog.pg_user")
# django_safeql.ValidationError: Unknown table: pg_catalog

transpiler.to_queryset("DELETE FROM book WHERE id = 1")
# django_safeql.UnsupportedSQL: ...
```

## How it works

`SQLToQuerySetTranspiler` runs SQL through four stages:

1. **Parse** — `sqlglot` parses the SQL text (Postgres dialect) into an
   internal AST.
2. **Annotate** — every column, join and function call is resolved against
   your `SQLTranspilerSchema` (including JSON Schema-typed JSON fields).
3. **Validate** — anything not explicitly whitelisted (unknown table,
   disallowed function, unsupported syntax, LIMIT above your ceiling, …)
   raises `ValidationError` or `UnsupportedSQL`.
4. **Codegen** — the validated AST is compiled into Django ORM constructs
   (`Q`, `F`, `Case`/`When`, `Subquery`, `Exists`, aggregates, JSON key
   transforms, casts, date truncation, …) and returned as a `QuerySet`.

## What's supported

- `SELECT` / `WHERE` / `JOIN` / `GROUP BY` / `HAVING` / `ORDER BY` / `LIMIT`
- Comparison, boolean and arithmetic operators
- Scalar aggregates (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) and Postgres
  collection aggregates (`ARRAY_AGG`, `STRING_AGG`, `JSON_AGG`, …)
- String functions (`LOWER`, `UPPER`, `TRIM`, `SUBSTRING`, `CONCAT`, …) and
  date functions (`EXTRACT`, `DATE_TRUNC`, …)
- Read-only JSON/JSONB access and functions, validated against a JSON
  Schema you provide per field
- `LATERAL` joins over `jsonb_array_elements`, `EXISTS` subqueries

Anything not explicitly listed — DDL, writes, arbitrary functions, joins to
undeclared tables — is rejected.

## License

MIT — see [LICENSE](LICENSE).
