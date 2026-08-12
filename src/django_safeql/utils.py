import sqlglot


def pretty_print_sql(sql: str) -> str:
    # Strip the "| params=..." suffix emitted by _render_sql_for_debug when mogrify is unavailable,
    # so sqlglot receives valid SQL. Params are appended as a comment after formatting.
    sql_body, sep, params_part = sql.partition(" | params=")
    try:
        formatted = sqlglot.transpile(sql_body, read="postgres", write="postgres", pretty=True)[0]
    except Exception:
        formatted = sql_body
    return f"{formatted}\n-- params: {params_part}" if sep else formatted
