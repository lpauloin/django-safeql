import pytest

# library: d1 print_run=2 (sqrt ≈ 1.4142), d2 print_run=4. SQRT gives a reliable float on
# every backend, so the fractional math cases avoid the integer-division gap (§4.2).


def _value(library, sql):
    raw = list(library.transpiler.to_queryset(f"{sql} WHERE book.id = {library.d1.id}"))[0]["r"]
    return float(raw)


def test_abs(library):
    assert _value(library, "SELECT ABS(book.print_run - 100) AS r FROM book") == 98.0


def test_sign(library):
    assert _value(library, "SELECT SIGN(book.print_run - 100) AS r FROM book") == -1.0


def test_sqrt(library):
    assert _value(library, "SELECT SQRT(book.print_run) AS r FROM book") == pytest.approx(1.41421, abs=1e-4)


def test_power(library):
    assert _value(library, "SELECT POWER(book.print_run, 3) AS r FROM book") == pytest.approx(8.0)


def test_floor(library):
    assert _value(library, "SELECT FLOOR(SQRT(book.print_run)) AS r FROM book") == 1.0


def test_ceil(library):
    assert _value(library, "SELECT CEIL(SQRT(book.print_run)) AS r FROM book") == 2.0


def test_round_with_precision(library):
    assert _value(library, "SELECT ROUND(SQRT(book.print_run), 2) AS r FROM book") == pytest.approx(1.41, abs=1e-9)


def test_round_without_precision(library):
    assert _value(library, "SELECT ROUND(SQRT(book.print_run)) AS r FROM book") == 1.0


def test_exp_and_ln_roundtrip(library):
    assert _value(library, "SELECT EXP(LN(book.print_run)) AS r FROM book") == pytest.approx(2.0, abs=1e-6)
