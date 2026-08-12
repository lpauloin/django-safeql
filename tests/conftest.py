from types import SimpleNamespace

import pytest

from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.schema_factory import make_codegen_schema, make_schema
from tests.testapp.models import Author, Award, Book, Publisher


@pytest.fixture
def transpiler():
    """Transpiler over the virtual schema — for parse/annotate/validate tests (no DB)."""
    return SQLToQuerySetTranspiler(make_schema())


@pytest.fixture
def library(db):
    """A small library catalog plus a transpiler over the real models — for codegen tests."""
    publisher_a = Publisher.objects.create(name="Acme")
    publisher_b = Publisher.objects.create(name="Beta")

    author_x = Author.objects.create(publisher=publisher_a, name="Ada Lovelace")
    author_y = Author.objects.create(publisher=publisher_a, name="Charles Babbage")
    author_z = Author.objects.create(publisher=publisher_b, name="Ada Lovelace")

    Award.objects.create(author=author_x, name="total", category="TEXT")
    Award.objects.create(author=author_x, name="currency", category="TEXT")

    d1 = Book.objects.create(
        author=author_x,
        status="PUBLISHED",
        title="letters-one.txt",
        print_run=2,
        metadata={
            "source": "email",
            "currency": "EUR",
            "total": "120.50",
            "lines": [{"label": "A", "amount": "100.50"}, {"label": "B", "amount": "20.00"}],
        },
    )
    d2 = Book.objects.create(
        author=author_x,
        status="PUBLISHED",
        title="letters-two.txt",
        print_run=4,
        metadata={"source": "api", "currency": "USD", "total": "80.00", "lines": []},
    )
    d3 = Book.objects.create(
        author=author_y,
        status="REJECTED",
        title="memo.txt",
        print_run=1,
        metadata={"source": "email", "currency": "EUR", "total": "5.00"},
    )
    d4 = Book.objects.create(
        author=author_z,
        status="PUBLISHED",
        title="letters-three.txt",
        print_run=5,
        metadata={"source": "email", "currency": "EUR", "total": "200.00"},
    )

    return SimpleNamespace(
        transpiler=SQLToQuerySetTranspiler(make_codegen_schema()),
        publisher_a=publisher_a,
        publisher_b=publisher_b,
        author_x=author_x,
        author_y=author_y,
        author_z=author_z,
        d1=d1,
        d2=d2,
        d3=d3,
        d4=d4,
    )
