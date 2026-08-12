import pytest

from django_safeql.exceptions import ValidationError


def test_rejects_unknown_table(transpiler):
    with pytest.raises(ValidationError, match="Unknown table"):
        transpiler.to_ast("SELECT * FROM unknown_table")


def test_rejects_star_on_unknown_table(transpiler):
    with pytest.raises(ValidationError, match="Unknown table"):
        transpiler.to_ast("SELECT unknown_table.* FROM book")


def test_rejects_non_base_from(transpiler):
    with pytest.raises(ValidationError, match="FROM must use base table"):
        transpiler.to_ast("SELECT publisher.* FROM publisher")


def test_rejects_unknown_field(transpiler):
    with pytest.raises(ValidationError, match="Unknown field"):
        transpiler.to_ast("SELECT book.* FROM book WHERE book.nope = 'x'")


def test_rejects_having_without_group_by(transpiler):
    with pytest.raises(ValidationError, match="HAVING requires GROUP BY"):
        transpiler.to_ast("SELECT COUNT(*) AS total FROM book HAVING COUNT(*) > 0")


def test_rejects_unsupported_function(transpiler):
    with pytest.raises(ValidationError, match="Unsupported SQL function"):
        transpiler.to_ast("SELECT book.* FROM book WHERE MD5(book.title) = 'abc'")


def test_rejects_bad_function_arity(transpiler):
    with pytest.raises(ValidationError, match="concat expects at least 2 arguments"):
        transpiler.to_ast("SELECT book.* FROM book WHERE CONCAT(book.title) = 'x'")


def test_rejects_unknown_json_field(transpiler):
    with pytest.raises(ValidationError, match="Field is not declared as JSON"):
        transpiler.to_ast("SELECT book.* FROM book WHERE book.title->>'x' = 'y'")


def test_rejects_excessive_limit(transpiler):
    with pytest.raises(ValidationError, match="LIMIT exceeds"):
        transpiler.to_ast("SELECT book.* FROM book LIMIT 5000")


def test_rejects_unsupported_cast_type(transpiler):
    with pytest.raises(ValidationError, match="Unsupported cast type"):
        transpiler.to_ast("SELECT book.pages::geometry AS g FROM book")
