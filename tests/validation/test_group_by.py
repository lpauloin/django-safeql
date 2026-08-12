"""SQL-standard GROUP BY coverage: every non-aggregate expression in
SELECT/HAVING/ORDER BY must be covered by the GROUP BY, or be rejected."""

import pytest

from django_safeql.exceptions import ValidationError


def test_rejects_bare_ungrouped_column_in_select(transpiler):
    with pytest.raises(ValidationError, match="must appear in GROUP BY"):
        transpiler.to_ast("SELECT book.status, book.pages, COUNT(*) AS c FROM book GROUP BY book.status")


def test_rejects_expression_with_ungrouped_leaf_in_select(transpiler):
    with pytest.raises(ValidationError, match="must appear in GROUP BY"):
        transpiler.to_ast("SELECT book.status, (book.pages + 1) AS p, COUNT(*) AS c FROM book GROUP BY book.status")


def test_rejects_having_on_ungrouped_non_aggregate(transpiler):
    with pytest.raises(ValidationError, match="HAVING may only reference"):
        transpiler.to_ast("SELECT book.status, COUNT(*) AS c FROM book GROUP BY book.status HAVING book.pages > 10")


def test_rejects_order_by_on_ungrouped_non_aggregate(transpiler):
    with pytest.raises(ValidationError, match="ORDER BY may only reference"):
        transpiler.to_ast("SELECT book.status, COUNT(*) AS c FROM book GROUP BY book.status ORDER BY book.pages DESC")


def test_rejects_star_with_group_by(transpiler):
    with pytest.raises(ValidationError, match="GROUP BY"):
        transpiler.to_ast("SELECT book.* FROM book GROUP BY book.status")


def test_rejects_order_by_bare_column_on_aggregate_without_group_by(transpiler):
    with pytest.raises(ValidationError, match="ORDER BY may only reference"):
        transpiler.to_ast("SELECT COUNT(*) AS c FROM book ORDER BY book.pages DESC")


def test_rejects_mixed_aggregate_and_bare_column_without_group_by(transpiler):
    with pytest.raises(ValidationError, match="must appear in GROUP BY"):
        transpiler.to_ast("SELECT book.status, COUNT(*) AS c FROM book")
