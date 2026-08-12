from tests.helpers import ids


def test_single_join_filter(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE author.name = 'Ada Lovelace'
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_multi_join_filter(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        JOIN publisher ON author.publisher_id = publisher.id
        WHERE publisher.name = 'Acme' AND author.name = 'Ada Lovelace' AND book.status = 'PUBLISHED'
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id, library.d2.id]


def test_join_with_alias(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.*
        FROM book AS d
        JOIN author AS p ON d.author_id = p.id
        JOIN publisher AS a ON p.publisher_id = a.id
        WHERE a.name = 'Beta'
        ORDER BY d.id ASC
    """)
    assert ids(qs) == [library.d4.id]
