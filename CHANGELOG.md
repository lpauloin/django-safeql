# Changelog

## [2.0.0] - 2026-08-31

### Added
- SQLite and MySQL support. Pass `target="sqlite"` or `target="mysql"` to
  `SQLToQuerySetTranspiler` (the default stays `"postgresql"`) and the same
  query compiles to a QuerySet for that backend. The target is checked against
  your queryset's database before anything runs, and a feature the backend
  cannot do is rejected with a clear error instead of failing at the database.
  The README lists what each backend supports.
- Math functions `ABS`, `CEIL`, `FLOOR`, `ROUND`, `POWER`, `SQRT`, `SIGN`,
  `EXP`, `LN`, and string functions `LEFT`, `RIGHT`, `REPEAT`, `REVERSE`,
  `LPAD`, `RPAD`.

### Changed
- `SQLToQuerySetTranspiler` takes an optional `target` argument. Code that does
  not pass one keeps running against PostgreSQL as before.
- On SQLite and MySQL, `ARRAY_AGG` returns a list built from a JSON array, since
  those backends have no native array type. The result is still a Python list.
- Runs on Django 4.2 through 6.1.

## [1.1.0] - 2026-08-12

### Security
- **Fixed a whitelist bypass.** A string literal beginning with `__field__:` was
  turned into a column reference, letting a query read fields and join to tables
  that were never declared in the schema. Such literals are now treated as plain
  values. Upgrading is strongly recommended for anyone running untrusted SQL.

### Fixed
- `GROUP BY` on a column that isn't repeated in `SELECT`
  (e.g. `SELECT COUNT(*) ... GROUP BY status`) now groups correctly instead of
  returning one row per record.
- Unsupported clauses inside `LATERAL`/`EXISTS` subqueries (`JOIN`, `GROUP BY`,
  `DISTINCT`, or a `LIMIT` other than 1) are now rejected instead of being
  silently ignored.
- Casting a `LATERAL` element to `timestamp` or `text` now produces valid SQL.
- A JSON path applied to an outer-table reference raises a clear error instead of
  crashing.
- Aliasing a `SELECT` column to a name that matches a model field
  (e.g. `... AS status`) raises a clear `ValidationError` instead of a low-level
  Django error.

### Changed
- Stricter, SQL-standard `GROUP BY` validation: every non-aggregate expression in
  `SELECT`, `HAVING` and `ORDER BY` must be covered by the `GROUP BY`, otherwise
  the query is rejected. Queries that were previously accepted but mis-compiled
  now raise `ValidationError`.
- Oversized or pathologically nested queries are rejected with `UnsupportedSQL`
  instead of surfacing a low-level error.

## [1.0.0]

- Initial release.
