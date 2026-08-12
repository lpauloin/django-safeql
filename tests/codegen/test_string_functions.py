from tests.helpers import ids


def test_lower_in_where(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE LOWER(book.title) = 'letters-one.txt'")
    assert ids(qs) == [library.d1.id]


def test_trim_in_where(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE LOWER(TRIM(book.title)) = 'letters-one.txt'")
    assert ids(qs) == [library.d1.id]


def test_length_in_where(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE LENGTH(book.title) > 11 ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d4.id]


def test_replace_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT REPLACE(book.title, 'letters', 'memo') AS renamed
        FROM book WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["renamed"] == "memo-one.txt"


def test_coalesce_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT COALESCE(book.title, 'fallback') AS display_name
        FROM book WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["display_name"] == "letters-one.txt"


def test_strpos_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT STRPOS(book.title, 'txt') AS pdf_pos
        FROM book WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["pdf_pos"] > 0


def test_concat_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT CONCAT(book.status, '-', book.title) AS label
        FROM book WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["label"] == "PUBLISHED-letters-one.txt"


def test_substring_in_select(library):
    qs = library.transpiler.to_queryset("""
        SELECT SUBSTRING(book.title FROM 1 FOR 7) AS prefix
        FROM book WHERE book.title = 'letters-one.txt'
    """)
    assert list(qs)[0]["prefix"] == "letters"
