from tests.helpers import ids


def test_json_text_path_filter(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.metadata->>'currency' = 'EUR' ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d3.id, library.d4.id]


def test_json_array_index_path(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.metadata->'lines'->0->>'amount' = '100.50'")
    assert ids(qs) == [library.d1.id]


def test_json_numeric_cast_filter(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE (book.metadata->>'total')::numeric > 100 ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d4.id]


def test_json_has_key(library):
    qs = library.transpiler.to_queryset("SELECT book.* FROM book WHERE book.metadata ? 'source' ORDER BY book.id ASC")
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]


def test_json_has_any_keys(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.metadata ?| array['unknown', 'currency'] ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]


def test_json_has_all_keys(library):
    qs = library.transpiler.to_queryset(
        "SELECT book.* FROM book WHERE book.metadata ?& array['source', 'currency'] ORDER BY book.id ASC"
    )
    assert ids(qs) == [library.d1.id, library.d2.id, library.d3.id, library.d4.id]
