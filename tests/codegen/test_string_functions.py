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


def _value(library, sql):
    return list(library.transpiler.to_queryset(f"{sql} WHERE book.id = {library.d1.id}"))[0]["r"]


def test_left(library):
    # d1 title = "letters-one.txt"
    assert _value(library, "SELECT LEFT(book.title, 7) AS r FROM book") == "letters"


def test_right(library):
    assert _value(library, "SELECT RIGHT(book.title, 3) AS r FROM book") == "txt"


def test_repeat(library):
    assert _value(library, "SELECT REPEAT(book.status, 2) AS r FROM book") == "PUBLISHEDPUBLISHED"


def test_reverse(library):
    assert _value(library, "SELECT REVERSE(book.status) AS r FROM book") == "DEHSILBUP"


def test_lpad(library):
    assert _value(library, "SELECT LPAD(book.status, 11, '-') AS r FROM book") == "--PUBLISHED"


def test_rpad(library):
    assert _value(library, "SELECT RPAD(book.status, 11, '-') AS r FROM book") == "PUBLISHED--"
