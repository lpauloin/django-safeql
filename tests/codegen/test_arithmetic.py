from tests.helpers import ids
from tests.testapp.models import Book


def test_arithmetic_in_where(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run * 2 + 1 > 8 ORDER BY book.id ASC")
    assert ids(qs) == [library.d2.id, library.d4.id]


def test_column_to_column_comparison(library):
    mismatch = Book.objects.create(
        author=library.author_x,
        status="PUBLISHED",
        title="mismatch.txt",
        print_run=0,
        review_count=5,
        metadata={},
    )
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE book.print_run >= book.review_count
        ORDER BY book.id ASC
    """)
    assert mismatch.id not in ids(qs)
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]
