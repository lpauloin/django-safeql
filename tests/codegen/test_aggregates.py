import pytest

from tests.helpers import assert_sql_contains


def test_case_when_inside_scalar_aggregates(library):
    library.d1.word_count = 100
    library.d2.word_count = 200
    library.d4.word_count = 300
    library.d1.save(update_fields=["word_count"])
    library.d2.save(update_fields=["word_count"])
    library.d4.save(update_fields=["word_count"])

    qs = library.transpiler.to_queryset("""
        SELECT COUNT(*) AS total_documents,
               SUM(CASE WHEN book.status = 'PUBLISHED' THEN 1 ELSE 0 END) AS parsed_ok_documents,
               SUM(CASE WHEN book.status = 'REJECTED' THEN 1 ELSE 0 END) AS parsed_ko_documents,
               AVG(CASE WHEN book.status = 'PUBLISHED' THEN book.print_run ELSE NULL END)
                   AS avg_prints_parsed_ok,
               AVG(CASE WHEN book.status = 'PUBLISHED' THEN book.word_count ELSE NULL END)
                   AS avg_content_length_parsed_ok
        FROM book
    """)

    row = list(qs)[0]
    assert row["total_documents"] == 4
    assert row["parsed_ok_documents"] == 3
    assert row["parsed_ko_documents"] == 1
    assert row["avg_prints_parsed_ok"] == pytest.approx((2 + 4 + 5) / 3)
    assert row["avg_content_length_parsed_ok"] == 200.0


def test_count_without_group_by(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.metadata ? 'source'")
    assert list(qs) == [{"total": 4}]


def test_count_without_group_by_returns_zero_for_empty_result(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.metadata ? 'missing'")
    assert list(qs) == [{"total": 0}]


def test_count_without_group_by_with_json_or_filter(library):
    qs = library.transpiler.to_queryset("""
        SELECT COUNT(*) AS total
        FROM book
        WHERE book.metadata ? 'missing' OR book.metadata ? 'currency'
    """)
    assert list(qs) == [{"total": 4}]


def test_text_cast_in_aggregate_filter(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE LENGTH(book.metadata::text) > 2")
    assert list(qs) == [{"total": 4}]


def test_jsonb_cast_in_aggregate_filter(library):
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.metadata != '{}'::jsonb")
    assert list(qs) == [{"total": 4}]


def test_count_with_having(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE book.status = 'PUBLISHED'
        GROUP BY author.id
        HAVING COUNT(*) > 1
        ORDER BY total DESC
    """)
    assert list(qs) == [{"author__id": library.author_x.id, "total": 2}]


def test_sum_avg_min_max(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id,
               SUM(book.print_run) AS prints_sum,
               AVG(book.print_run) AS prints_avg,
               MIN(book.print_run) AS prints_min,
               MAX(book.print_run) AS prints_max
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        ORDER BY author.id ASC
    """)
    by_author = {row["author__id"]: row for row in qs}
    assert by_author[library.author_x.id]["prints_sum"] == 6
    assert by_author[library.author_x.id]["prints_min"] == 2
    assert by_author[library.author_x.id]["prints_max"] == 4
    assert by_author[library.author_y.id]["prints_sum"] == 1
    assert by_author[library.author_z.id]["prints_sum"] == 5


def test_count_deduplication_in_select_and_having(library):
    qs = library.transpiler.to_queryset("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        HAVING COUNT(*) >= 1
        ORDER BY total DESC
    """)
    assert_sql_contains(qs, "GROUP BY", "COUNT", "HAVING")
    rows = list(qs)
    assert {row["author__id"] for row in rows} == {library.author_x.id, library.author_y.id, library.author_z.id}


def test_group_by_column_not_in_select_still_groups(library):
    # A GROUP BY on a column that isn't also in the SELECT list used to be silently
    # dropped, turning the query into one group per row instead of per status.
    qs = library.transpiler.to_queryset("SELECT COUNT(*) AS cnt FROM book GROUP BY book.status")
    assert_sql_contains(qs, "GROUP BY")
    counts = {row["status"]: row["cnt"] for row in qs}
    assert counts == {"PUBLISHED": 3, "REJECTED": 1}


def test_expression_over_grouped_column(library):
    # LOWER(status) is covered because its only column leaf (status) is grouped.
    qs = library.transpiler.to_queryset(
        "SELECT LOWER(book.status) AS s, COUNT(*) AS cnt FROM book GROUP BY book.status"
    )
    counts = {row["s"]: row["cnt"] for row in qs}
    assert counts == {"published": 3, "rejected": 1}


def test_having_on_grouped_column(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.status, COUNT(*) AS c
        FROM book
        GROUP BY book.status
        HAVING book.status = 'PUBLISHED'
    """)
    counts = {row["status"]: row["c"] for row in qs}
    assert counts == {"PUBLISHED": 3}


def test_order_by_grouped_column(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.status, COUNT(*) AS c
        FROM book
        GROUP BY book.status
        ORDER BY book.status ASC
    """)
    assert [row["status"] for row in qs] == ["PUBLISHED", "REJECTED"]


def test_multi_column_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.author_id, book.status, COUNT(*) AS c
        FROM book
        GROUP BY book.author_id, book.status
    """)
    buckets = {(row["author_id"], row["status"]): row["c"] for row in qs}
    assert buckets[(library.author_x.id, "PUBLISHED")] == 2
    assert buckets[(library.author_y.id, "REJECTED")] == 1
    assert buckets[(library.author_z.id, "PUBLISHED")] == 1
