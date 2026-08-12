"""Joining through book -> author -> award_set."""

import pytest

from tests.testapp.models import Award


@pytest.fixture
def awards(library):
    # Mark one award official, add another that is not featured.
    Award.objects.filter(author=library.author_x, name="total").update(is_official=True)
    Award.objects.create(
        author=library.author_x,
        name="genre",
        category="ONELINE",
        is_official=False,
        is_featured=False,
    )
    return library


def test_distinct_names(awards):
    qs = awards.transpiler.to_queryset(f"""
        SELECT DISTINCT award.name FROM book
        WHERE book.author_id = {awards.author_x.id}
        ORDER BY award.name ASC
    """)
    names = [r["author__award_set__name"] for r in list(qs)]
    assert names == ["currency", "genre", "total"]


def test_category_list(awards):
    qs = awards.transpiler.to_queryset("""
        SELECT DISTINCT award.name AS fname, award.category AS fmt
        FROM book
        WHERE book.status = 'PUBLISHED'
        ORDER BY award.name ASC
    """)
    by_name = {r["fname"]: r["fmt"] for r in qs}
    assert by_name["total"] == "TEXT"
    assert by_name["currency"] == "TEXT"
    assert by_name["genre"] == "ONELINE"


def test_official_filter(awards):
    qs = awards.transpiler.to_queryset("""
        SELECT DISTINCT award.name AS fname FROM book
        WHERE award.is_official = TRUE
        ORDER BY award.name ASC
    """)
    assert [r["fname"] for r in qs] == ["total"]


def test_not_featured(awards):
    qs = awards.transpiler.to_queryset("""
        SELECT DISTINCT award.name AS fname FROM book
        WHERE award.is_featured = FALSE
        ORDER BY award.name ASC
    """)
    assert [r["fname"] for r in qs] == ["genre"]


def test_count(awards):
    # 3 awards x 2 PUBLISHED docs = 6 rows -> GROUP BY name gives 3 buckets of 2.
    qs = awards.transpiler.to_queryset(f"""
        SELECT award.name AS fname, COUNT(*) AS doc_count
        FROM book
        WHERE book.status = 'PUBLISHED' AND book.author_id = {awards.author_x.id}
        GROUP BY fname
        ORDER BY fname ASC
    """)
    rows = list(qs)
    assert len(rows) == 3
    assert all(r["doc_count"] == 2 for r in rows)


def test_author_id_matches(awards):
    qs = awards.transpiler.to_queryset(f"""
        SELECT DISTINCT award.author_id AS pid FROM book
        WHERE book.author_id = {awards.author_x.id}
          AND award.author_id IS NOT NULL
    """)
    pids = {r["pid"] for r in qs}
    assert awards.author_x.id in pids
    assert awards.author_y.id not in pids
    assert awards.author_z.id not in pids
