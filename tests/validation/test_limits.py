"""Guards against untrusted input exhausting the interpreter (DoS)."""

import pytest

from django_safeql.exceptions import UnsupportedSQL


def test_deeply_nested_expression_is_rejected_not_a_recursion_error(transpiler):
    # A pathologically nested expression must surface as UnsupportedSQL, never as a
    # raw RecursionError leaking out of the parser or a visitor.
    deep = "book.pages" + " + 1" * 5000
    with pytest.raises(UnsupportedSQL, match="too deeply nested"):
        transpiler.to_ast(f"SELECT book.id FROM book WHERE {deep} > 0")


def test_oversized_input_is_rejected(transpiler):
    huge = "SELECT book.id FROM book WHERE book.title = '" + "a" * 100_001 + "'"
    with pytest.raises(UnsupportedSQL, match="maximum supported length"):
        transpiler.to_ast(huge)
