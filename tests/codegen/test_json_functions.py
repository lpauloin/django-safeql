import json

from tests.helpers import ids
from tests.testapp.models import Book

# --- jsonb_typeof ---


def test_jsonb_typeof_array(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_typeof(book.metadata->'lines') AS t
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["t"] == "array"


def test_jsonb_typeof_string(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_typeof(book.metadata->'currency') AS t
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["t"] == "string"


def test_jsonb_typeof_in_where(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_typeof(book.metadata->'lines') = 'array'
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id, library.d2.id]


# --- jsonb_extract_path ---


def test_jsonb_extract_path_single_key(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_extract_path(book.metadata, 'currency') AS val
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["val"] == "EUR"


def test_jsonb_extract_path_nested(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_extract_path(book.metadata, 'lines', '0') AS first_line
        FROM book WHERE book.id = {library.d1.id}
    """)
    result = list(qs)[0]["first_line"]
    assert result is not None
    if isinstance(result, str):
        result = json.loads(result)
    assert result["label"] == "A"


# --- jsonb_extract_path_text ---


def test_jsonb_extract_path_text_single_key(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_extract_path_text(book.metadata, 'currency') AS val
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["val"] == "EUR"


def test_jsonb_extract_path_text_in_where(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_extract_path_text(book.metadata, 'currency') = 'USD'
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d2.id]


def test_jsonb_extract_path_text_nested(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_extract_path_text(book.metadata, 'lines', '0', 'label') AS lbl
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["lbl"] == "A"


# --- jsonb_strip_nulls ---


def test_jsonb_strip_nulls_removes_null_fields(library):
    doc = Book.objects.create(
        author=library.author_x,
        status="PUBLISHED",
        title="null-test.txt",
        print_run=1,
        metadata={"currency": "EUR", "ref": None, "total": "10.00"},
    )
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_strip_nulls(book.metadata) AS clean
        FROM book WHERE book.id = {doc.id}
    """)
    result = list(qs)[0]["clean"]
    assert "ref" not in result
    assert "currency" in result


def test_jsonb_strip_nulls_no_nulls_unchanged(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_strip_nulls(book.metadata) AS clean
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["clean"]["currency"] == "EUR"


# --- jsonb_pretty ---


def test_jsonb_pretty_returns_indented_text(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_pretty(book.metadata) AS pretty
        FROM book WHERE book.id = {library.d1.id}
    """)
    pretty = list(qs)[0]["pretty"]
    assert isinstance(pretty, str)
    assert "\n" in pretty
    assert "EUR" in pretty


# --- jsonb_path_exists ---


def test_jsonb_path_exists_true(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_path_exists(book.metadata, '$.lines') AS has_lines
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["has_lines"]


def test_jsonb_path_exists_false(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_path_exists(book.metadata, '$.lines') AS has_lines
        FROM book WHERE book.id = {library.d3.id}
    """)
    assert not list(qs)[0]["has_lines"]


def test_jsonb_path_exists_in_where(library):
    qs = library.transpiler.to_queryset("""
        SELECT book.* FROM book
        WHERE jsonb_path_exists(book.metadata, '$.lines') = TRUE
        ORDER BY book.id ASC
    """)
    assert ids(qs) == [library.d1.id, library.d2.id]


# --- jsonb_path_query_first ---


def test_jsonb_path_query_first_returns_value(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_path_query_first(book.metadata, '$.lines[0]') AS first_line
        FROM book WHERE book.id = {library.d1.id}
    """)
    result = list(qs)[0]["first_line"]
    if isinstance(result, str):
        result = json.loads(result)
    assert result["label"] == "A"


def test_jsonb_path_query_first_empty_array_returns_null(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_path_query_first(book.metadata, '$.lines[0]') AS first_line
        FROM book WHERE book.id = {library.d2.id}
    """)
    assert list(qs)[0]["first_line"] is None


def test_jsonb_path_query_first_scalar_value(library):
    qs = library.transpiler.to_queryset(f"""
        SELECT jsonb_path_query_first(book.metadata, '$.currency') AS cur
        FROM book WHERE book.id = {library.d1.id}
    """)
    assert list(qs)[0]["cur"] == "EUR"
