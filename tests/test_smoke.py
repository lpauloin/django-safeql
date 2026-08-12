from django.test import TestCase

from django_safeql import SQLToQuerySetTranspiler, UnsupportedSQL, ValidationError
from tests.schema_factory import make_codegen_schema
from tests.testapp.models import Author, Book, Publisher


class SmokeTestCase(TestCase):
    def setUp(self):
        self.publisher = Publisher.objects.create(name="Acme Press", is_active=True)
        self.author = Author.objects.create(name="Ada Lovelace", publisher=self.publisher)
        Book.objects.create(
            title="Notes on the Analytical Engine",
            isbn="111",
            status="published",
            author=self.author,
            publisher=self.publisher,
            pages=42,
            price="9.99",
            details={"language": "en", "edition": 1},
        )
        Book.objects.create(
            title="Sketch of the Analytical Engine",
            isbn="222",
            status="draft",
            author=self.author,
            publisher=self.publisher,
            pages=17,
            price="4.50",
            details={"language": "fr", "edition": 2},
        )
        self.transpiler = SQLToQuerySetTranspiler(make_codegen_schema())

    def test_select_where_orders_and_limits(self):
        qs = self.transpiler.to_queryset(
            "SELECT id, title, pages FROM book WHERE status = 'published' ORDER BY pages DESC LIMIT 10"
        )
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Notes on the Analytical Engine")

    def test_join_and_aggregate(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.name AS author_name, COUNT(*) AS book_count
              FROM book
              JOIN author ON book.author_id = author.id
             GROUP BY author.name
            """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author_name"], "Ada Lovelace")
        self.assertEqual(rows[0]["book_count"], 2)

    def test_json_field_access(self):
        qs = self.transpiler.to_queryset("SELECT id FROM book WHERE details->>'language' = 'fr'")
        rows = list(qs)
        self.assertEqual(len(rows), 1)

    def test_rejects_unlisted_table(self):
        with self.assertRaises(ValidationError):
            self.transpiler.to_queryset("SELECT * FROM pg_catalog.pg_user")

    def test_rejects_unsupported_syntax(self):
        with self.assertRaises(UnsupportedSQL):
            self.transpiler.to_queryset("DELETE FROM book WHERE id = 1")
