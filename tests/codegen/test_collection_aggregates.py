import pytest

from django_safeql.exceptions import ValidationError


def test_array_agg_no_group_by(library):
    qs = library.transpiler.to_queryset(
        "SELECT ARRAY_AGG(book.title) AS names FROM book WHERE book.status = 'PUBLISHED'"
    )
    row = list(qs)[0]
    assert isinstance(row["names"], list)
    assert sorted(row["names"]) == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])


def test_array_agg_distinct(library):
    qs = library.transpiler.to_queryset("SELECT ARRAY_AGG(DISTINCT book.status) AS statuses FROM book")
    row = list(qs)[0]
    assert isinstance(row["statuses"], list)
    assert sorted(row["statuses"]) == sorted(["PUBLISHED", "REJECTED"])


def test_array_agg_with_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.status, ARRAY_AGG(book.title) AS names
        FROM book
        GROUP BY book.status
        ORDER BY book.status
    """)
    rows = {r["status"]: r["names"] for r in qs}
    assert sorted(rows["PUBLISHED"]) == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])
    assert sorted(rows["REJECTED"]) == ["memo.txt"]


def test_array_agg_order_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT ARRAY_AGG(book.title ORDER BY book.title ASC) AS names
        FROM book
        WHERE book.status = 'PUBLISHED'
    """)
    row = list(qs)[0]
    assert row["names"] == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])


def test_string_agg_no_group_by(library):
    qs = library.transpiler.to_queryset("SELECT STRING_AGG(book.status, ', ') AS statuses FROM book")
    row = list(qs)[0]
    assert isinstance(row["statuses"], str)
    for status in ("PUBLISHED", "REJECTED"):
        assert status in row["statuses"]


def test_string_agg_with_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.status, STRING_AGG(book.title, ' | ') AS names
        FROM book
        GROUP BY book.status
        ORDER BY book.status
    """)
    rows = {r["status"]: r["names"] for r in qs}
    assert "letters-one.txt" in rows["PUBLISHED"]
    assert "|" in rows["PUBLISHED"]
    assert rows["REJECTED"] == "memo.txt"


def test_json_agg_no_group_by(library):
    qs = library.transpiler.to_queryset(
        "SELECT JSON_AGG(book.title) AS names FROM book WHERE book.status = 'PUBLISHED'"
    )
    row = list(qs)[0]
    assert isinstance(row["names"], list)
    assert sorted(row["names"]) == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])


def test_jsonb_agg_no_group_by(library):
    qs = library.transpiler.to_queryset(
        "SELECT JSONB_AGG(book.title) AS names FROM book WHERE book.status = 'PUBLISHED'"
    )
    row = list(qs)[0]
    assert isinstance(row["names"], list)
    assert sorted(row["names"]) == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])


def test_json_object_agg_no_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT JSON_OBJECT_AGG(book.title, book.print_run) AS doc_credits
        FROM book
        WHERE book.status = 'PUBLISHED'
    """)
    row = list(qs)[0]
    assert isinstance(row["doc_credits"], dict)
    assert row["doc_credits"]["letters-one.txt"] == 2
    assert row["doc_credits"]["letters-two.txt"] == 4


def test_jsonb_object_agg_no_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT JSONB_OBJECT_AGG(book.title, book.print_run) AS doc_credits
        FROM book
        WHERE book.status = 'PUBLISHED'
    """)
    row = list(qs)[0]
    assert isinstance(row["doc_credits"], dict)
    assert row["doc_credits"]["letters-one.txt"] == 2


def test_json_agg_with_group_by(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.status, JSON_AGG(book.title) AS names
        FROM book
        GROUP BY book.status
        ORDER BY book.status
    """)
    rows = {r["status"]: r["names"] for r in qs}
    assert sorted(rows["PUBLISHED"]) == sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"])
    assert sorted(rows["REJECTED"]) == ["memo.txt"]


def test_array_agg_rejects_unsupported_function(library):
    with pytest.raises(ValidationError):
        library.transpiler.to_queryset("SELECT ARRAY_AGG(UNKNOWN_FN(book.title)) FROM book")
