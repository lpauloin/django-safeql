import datetime

# --- NOW() / CURRENT_TIMESTAMP ---


def test_now_filter_all_docs_before_now(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.created < NOW()")
    assert list(qs)[0]["total"] == 4


def test_now_filter_no_docs_after_now(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.created > NOW()")
    assert list(qs)[0]["total"] == 0


# --- EXTRACT ---


def test_extract_year_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(YEAR FROM book.created) AS yr FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["yr"] == datetime.datetime.now().year


def test_extract_month_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(MONTH FROM book.created) AS mo FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["mo"] == datetime.datetime.now().month


def test_extract_day_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(DAY FROM book.created) AS dy FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["dy"] == datetime.datetime.now().day


def test_extract_quarter_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(QUARTER FROM book.created) AS q FROM book WHERE book.id = {library.d1.id}"
    )
    expected_quarter = (datetime.datetime.now().month - 1) // 3 + 1
    assert list(qs)[0]["q"] == expected_quarter


def test_extract_week_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(WEEK FROM book.created) AS wk FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["wk"] is not None


def test_extract_hour_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(HOUR FROM book.created) AS hr FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["hr"] is not None


def test_extract_minute_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(MINUTE FROM book.created) AS mn FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["mn"] is not None


def test_extract_second_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT EXTRACT(SECOND FROM book.created) AS sc FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["sc"] is not None


def test_extract_all_parts_in_one_select(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT EXTRACT(YEAR FROM book.created) AS yr,
               EXTRACT(QUARTER FROM book.created) AS q,
               EXTRACT(MONTH FROM book.created) AS mo,
               EXTRACT(WEEK FROM book.created) AS wk,
               EXTRACT(DAY FROM book.created) AS dy,
               EXTRACT(HOUR FROM book.created) AS hr,
               EXTRACT(MINUTE FROM book.created) AS mn,
               EXTRACT(SECOND FROM book.created) AS sc
        FROM book WHERE book.id = {library.d1.id}
    """)
    row = list(qs)[0]
    now = datetime.datetime.now()
    assert row["yr"] == now.year
    assert row["mo"] == now.month
    assert row["dy"] == now.day


def test_extract_year_in_where(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT COUNT(*) AS total FROM book
        WHERE EXTRACT(YEAR FROM book.created) = {datetime.datetime.now().year}
    """)
    assert list(qs)[0]["total"] == 4


# --- date_trunc ---


def test_trunc_year_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('year', book.created) AS yr FROM book WHERE book.id = {library.d1.id}"
    )
    assert isinstance(list(qs)[0]["yr"], (datetime.datetime, datetime.date))


def test_trunc_quarter_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('quarter', book.created) AS q FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["q"] is not None


def test_trunc_month_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('month', book.created) AS mo FROM book WHERE book.id = {library.d1.id}"
    )
    assert isinstance(list(qs)[0]["mo"], (datetime.datetime, datetime.date))


def test_trunc_week_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('week', book.created) AS wk FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["wk"] is not None


def test_trunc_day_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('day', book.created) AS dy FROM book WHERE book.id = {library.d1.id}"
    )
    assert isinstance(list(qs)[0]["dy"], (datetime.datetime, datetime.date))


def test_trunc_hour_in_select(library):
    qs = library.transpiler.to_queryset(
        f"SELECT date_trunc('hour', book.created) AS hr FROM book WHERE book.id = {library.d1.id}"
    )
    assert list(qs)[0]["hr"] is not None


def test_trunc_month_in_where_matches_all_docs(library):
    qs = library.transpiler.to_queryset("""
        SELECT COUNT(*) AS total FROM book
        WHERE date_trunc('month', book.created) = date_trunc('month', NOW())
    """)
    assert list(qs)[0]["total"] == 4


def test_trunc_year_in_where_matches_all_docs(library):
    qs = library.transpiler.to_queryset("""
        SELECT COUNT(*) AS total FROM book
        WHERE date_trunc('year', book.created) = date_trunc('year', NOW())
    """)
    assert list(qs)[0]["total"] == 4


# --- GROUP BY with date functions ---


def test_extract_year_group_by_single_bucket(library):
    qs = library.transpiler.to_queryset("""
        SELECT EXTRACT(YEAR FROM book.created) AS yr, COUNT(*) AS total
        FROM book
        GROUP BY yr
        ORDER BY yr ASC
    """)
    rows = list(qs)
    assert len(rows) == 1
    assert rows[0]["total"] == 4


def test_extract_month_group_by_single_bucket(library):
    qs = library.transpiler.to_queryset("""
        SELECT EXTRACT(YEAR FROM book.created) AS yr,
               EXTRACT(MONTH FROM book.created) AS mo,
               COUNT(*) AS total
        FROM book
        GROUP BY yr, mo
        ORDER BY yr, mo
    """)
    rows = list(qs)
    assert len(rows) == 1
    assert rows[0]["total"] == 4


def test_trunc_month_group_by_single_bucket(library):
    qs = library.transpiler.to_queryset("""
        SELECT date_trunc('month', book.created) AS period, COUNT(*) AS total
        FROM book
        GROUP BY period
        ORDER BY period ASC
    """)
    rows = list(qs)
    assert len(rows) == 1
    assert rows[0]["total"] == 4


# --- Combinations ---


def test_extract_in_aggregate_having(library):
    qs = library.transpiler.to_queryset("""
        SELECT EXTRACT(YEAR FROM book.created) AS yr, COUNT(*) AS total
        FROM book
        GROUP BY yr
        HAVING COUNT(*) > 0
        ORDER BY yr ASC
    """)
    assert len(list(qs)) == 1


def test_trunc_and_extract_combined(library):
    qs = library.transpiler.to_queryset("""
        SELECT date_trunc('month', book.created) AS period,
               EXTRACT(MONTH FROM book.created) AS mo,
               COUNT(*) AS total
        FROM book
        WHERE book.created < NOW()
        GROUP BY period, mo
        ORDER BY period ASC
    """)
    rows = list(qs)
    assert len(rows) == 1
    assert rows[0]["total"] == 4
