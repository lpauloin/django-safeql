import datetime

from django.test import TestCase

from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.schema_factory import make_codegen_schema
from tests.testapp.models import Author, Award, Book, Publisher


class SQLCodegenBaseTestCase(TestCase):
    def setUp(self):
        self.publisher_a = Publisher(name="Acme")
        self.publisher_a.save()
        self.publisher_b = Publisher(name="Beta")
        self.publisher_b.save()

        self.author_x = Author.objects.create(publisher=self.publisher_a, name="Ada Lovelace")
        self.author_y = Author.objects.create(publisher=self.publisher_a, name="Charles Babbage")
        self.author_z = Author.objects.create(publisher=self.publisher_b, name="Ada Lovelace")

        Award.objects.create(author=self.author_x, name="total", category="TEXT")
        Award.objects.create(author=self.author_x, name="currency", category="TEXT")

        self.d1 = Book.objects.create(
            author=self.author_x,
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
        self.d2 = Book.objects.create(
            author=self.author_x,
            status="PUBLISHED",
            title="letters-two.txt",
            print_run=4,
            metadata={"source": "api", "currency": "USD", "total": "80.00", "lines": []},
        )
        self.d3 = Book.objects.create(
            author=self.author_y,
            status="REJECTED",
            title="memo.txt",
            print_run=1,
            metadata={"source": "email", "currency": "EUR", "total": "5.00"},
        )
        self.d4 = Book.objects.create(
            author=self.author_z,
            status="PUBLISHED",
            title="letters-three.txt",
            print_run=5,
            metadata={"source": "email", "currency": "EUR", "total": "200.00"},
        )
        self.transpiler = SQLToQuerySetTranspiler(make_codegen_schema())

    def ids(self, qs):
        return list(qs.values_list("id", flat=True))

    def assertSqlContains(self, qs, *fragments):
        sql, params = qs.query.sql_with_params()
        normalized = " ".join(sql.upper().split())
        for fragment in fragments:
            self.assertIn(fragment.upper(), normalized)
        return sql, params


# ---------------------------------------------------------------------------
# 1. Filters
# ---------------------------------------------------------------------------


class SQLCodegenFilterTestCase(SQLCodegenBaseTestCase):
    def test_equality(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_not_equal(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.status != 'REJECTED' ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_comparison_operators(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run > 2 ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d2.id, self.d4.id])

        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run >= 4 ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d2.id, self.d4.id])

        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run < 4 ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d3.id])

        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.print_run <= 2 ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d3.id])

    def test_in_operator(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.status IN ('PUBLISHED', 'REJECTED') ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])

    def test_is_null_and_is_not_null(self):
        self.d1.word_count = 123
        self.d1.save(update_fields=["word_count"])

        qs_not_null = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.word_count IS NOT NULL")
        qs_null = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.word_count IS NULL ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs_not_null), [self.d1.id])
        self.assertEqual(self.ids(qs_null), [self.d2.id, self.d3.id, self.d4.id])

    def test_and_or_not(self):
        qs_and = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE book.status = 'PUBLISHED' AND book.print_run >= 4
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs_and), [self.d2.id, self.d4.id])

        qs_or = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE book.status = 'REJECTED' OR book.print_run >= 4
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs_or), [self.d2.id, self.d3.id, self.d4.id])

        qs_not = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE NOT book.print_run < 4
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs_not), [self.d2.id, self.d4.id])

    def test_like_startswith(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.title LIKE 'letters-%' ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_like_endswith(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.title LIKE '%.txt' ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])

    def test_like_contains(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.title LIKE '%memo%' ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d3.id])

    def test_ilike_case_insensitive(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.title ILIKE '%LETTERS%' ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_like_complex_internal_wildcard(self):
        # Pattern with internal % — 'letters%.txt' matches all invoice-*.pdf files
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.title LIKE 'letters%.txt' ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_like_exact_match(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.title LIKE 'letters-one.txt' ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id])


# ---------------------------------------------------------------------------
# 2. JOINs
# ---------------------------------------------------------------------------


class SQLCodegenJoinTestCase(SQLCodegenBaseTestCase):
    def test_single_join_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE author.name = 'Ada Lovelace'
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_multi_join_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            JOIN publisher ON author.publisher_id = publisher.id
            WHERE publisher.name = 'Acme' AND author.name = 'Ada Lovelace' AND book.status = 'PUBLISHED'
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id])

    def test_join_with_alias(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.*
            FROM book AS d
            JOIN author AS p ON d.author_id = p.id
            JOIN publisher AS a ON p.publisher_id = a.id
            WHERE a.name = 'Beta'
            ORDER BY d.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d4.id])


# ---------------------------------------------------------------------------
# 3. Arithmetic
# ---------------------------------------------------------------------------


class SQLCodegenArithmeticTestCase(SQLCodegenBaseTestCase):
    def test_arithmetic_in_where(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.print_run * 2 + 1 > 8 ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d2.id, self.d4.id])

    def test_column_to_column_comparison(self):
        mismatch = Book.objects.create(
            author=self.author_x,
            status="PUBLISHED",
            title="mismatch.txt",
            print_run=0,
            review_count=5,
            metadata={},
        )
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE book.print_run >= book.review_count
            ORDER BY book.id ASC
        """)
        self.assertNotIn(mismatch.id, self.ids(qs))
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])


# ---------------------------------------------------------------------------
# 4. String functions
# ---------------------------------------------------------------------------


class SQLCodegenStringFunctionTestCase(SQLCodegenBaseTestCase):
    def test_lower_in_where(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE LOWER(book.title) = 'letters-one.txt'")
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_trim_in_where(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE LOWER(TRIM(book.title)) = 'letters-one.txt'")
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_length_in_where(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE LENGTH(book.title) > 11 ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_replace_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT REPLACE(book.title, 'letters', 'memo') AS renamed
            FROM book WHERE book.title = 'letters-one.txt'
        """)
        self.assertEqual(list(qs)[0]["renamed"], "memo-one.txt")

    def test_coalesce_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT COALESCE(book.title, 'fallback') AS display_name
            FROM book WHERE book.title = 'letters-one.txt'
        """)
        self.assertEqual(list(qs)[0]["display_name"], "letters-one.txt")

    def test_strpos_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT STRPOS(book.title, 'txt') AS pdf_pos
            FROM book WHERE book.title = 'letters-one.txt'
        """)
        self.assertGreater(list(qs)[0]["pdf_pos"], 0)

    def test_concat_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT CONCAT(book.status, '-', book.title) AS label
            FROM book WHERE book.title = 'letters-one.txt'
        """)
        self.assertEqual(list(qs)[0]["label"], "PUBLISHED-letters-one.txt")

    def test_substring_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT SUBSTRING(book.title FROM 1 FOR 7) AS prefix
            FROM book WHERE book.title = 'letters-one.txt'
        """)
        self.assertEqual(list(qs)[0]["prefix"], "letters")


# ---------------------------------------------------------------------------
# 5. JSON
# ---------------------------------------------------------------------------


class SQLCodegenJsonTestCase(SQLCodegenBaseTestCase):
    def test_json_text_path_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.metadata->>'currency' = 'EUR' ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d3.id, self.d4.id])

    def test_json_array_index_path(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.metadata->'lines'->0->>'amount' = '100.50'
        """)
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_json_numeric_cast_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE (book.metadata->>'total')::numeric > 100 ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d4.id])

    def test_json_has_key(self):
        qs = self.transpiler.to_queryset("SELECT book.* FROM book WHERE book.metadata ? 'source' ORDER BY book.id ASC")
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])

    def test_json_has_any_keys(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.metadata ?| array['unknown', 'currency'] ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])

    def test_json_has_all_keys(self):
        qs = self.transpiler.to_queryset(
            "SELECT book.* FROM book WHERE book.metadata ?& array['source', 'currency'] ORDER BY book.id ASC"
        )
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d3.id, self.d4.id])


# ---------------------------------------------------------------------------
# 6. Aggregates and GROUP BY
# ---------------------------------------------------------------------------


class SQLCodegenAggregateTestCase(SQLCodegenBaseTestCase):
    def test_case_when_inside_scalar_aggregates(self):
        self.d1.word_count = 100
        self.d2.word_count = 200
        self.d4.word_count = 300
        self.d1.save(update_fields=["word_count"])
        self.d2.save(update_fields=["word_count"])
        self.d4.save(update_fields=["word_count"])

        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total_documents,
                   SUM(CASE WHEN book.status = 'PUBLISHED' THEN 1 ELSE 0 END) AS parsed_ok_documents,
                   SUM(CASE WHEN book.status = 'REJECTED' THEN 1 ELSE 0 END) AS parsed_ko_documents,
                   AVG(CASE WHEN book.status = 'PUBLISHED' THEN book.print_run ELSE NULL END)
                       AS avg_prints_parsed_ok,
                   AVG(CASE WHEN book.status = 'PUBLISHED' THEN book.word_count ELSE NULL END)
                       AS avg_content_length_parsed_ok
            FROM book
        """)

        row = list(qs)[0]
        self.assertEqual(4, row["total_documents"])
        self.assertEqual(3, row["parsed_ok_documents"])
        self.assertEqual(1, row["parsed_ko_documents"])
        self.assertAlmostEqual((2 + 4 + 5) / 3, row["avg_prints_parsed_ok"])
        self.assertEqual(200.0, row["avg_content_length_parsed_ok"])

    def test_count_without_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total
            FROM book
            WHERE book.metadata ? 'source'
        """)
        self.assertEqual(list(qs), [{"total": 4}])

    def test_count_without_group_by_returns_zero_for_empty_result(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total
            FROM book
            WHERE book.metadata ? 'missing'
        """)
        self.assertEqual(list(qs), [{"total": 0}])

    def test_count_without_group_by_with_json_or_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total
            FROM book
            WHERE book.metadata ? 'missing' OR book.metadata ? 'currency'
        """)
        self.assertEqual(list(qs), [{"total": 4}])

    def test_text_cast_in_aggregate_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total
            FROM book
            WHERE LENGTH(book.metadata::text) > 2
        """)
        self.assertEqual(list(qs), [{"total": 4}])

    def test_jsonb_cast_in_aggregate_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total
            FROM book
            WHERE book.metadata != '{}'::jsonb
        """)
        self.assertEqual(list(qs), [{"total": 4}])

    def test_count_with_having(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.status = 'PUBLISHED'
            GROUP BY author.id
            HAVING COUNT(*) > 1
            ORDER BY total DESC
        """)
        self.assertEqual(list(qs), [{"author__id": self.author_x.id, "total": 2}])

    def test_sum_avg_min_max(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id,
                   SUM(book.print_run) AS prints_sum,
                   AVG(book.print_run) AS prints_avg,
                   MIN(book.print_run) AS prints_min,
                   MAX(book.print_run) AS prints_max
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            ORDER BY author.id ASC
        """)
        by_author = {row["author__id"]: row for row in qs}
        self.assertEqual(by_author[self.author_x.id]["prints_sum"], 6)
        self.assertEqual(by_author[self.author_x.id]["prints_min"], 2)
        self.assertEqual(by_author[self.author_x.id]["prints_max"], 4)
        self.assertEqual(by_author[self.author_y.id]["prints_sum"], 1)
        self.assertEqual(by_author[self.author_z.id]["prints_sum"], 5)

    def test_count_deduplication_in_select_and_having(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            HAVING COUNT(*) >= 1
            ORDER BY total DESC
        """)
        self.assertSqlContains(qs, "GROUP BY", "COUNT", "HAVING")
        rows = list(qs)
        self.assertEqual({row["author__id"] for row in rows}, {self.author_x.id, self.author_y.id, self.author_z.id})

    def test_group_by_column_not_in_select_still_groups(self):
        # Regression test: GROUP BY on a column that isn't also in the SELECT list
        # (very ordinary SQL, e.g. "SELECT COUNT(*) ... GROUP BY status") used to be
        # silently dropped, turning the query into one group per row instead of one
        # group per distinct status.
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS cnt
            FROM book
            GROUP BY book.status
        """)
        self.assertSqlContains(qs, "GROUP BY")
        counts = {row["status"]: row["cnt"] for row in qs}
        # d1, d2, d4 are PUBLISHED; d3 is REJECTED.
        self.assertEqual(counts, {"PUBLISHED": 3, "REJECTED": 1})


# ---------------------------------------------------------------------------
# 7. Collection aggregates — ARRAY_AGG, STRING_AGG, JSON_AGG, etc.
# ---------------------------------------------------------------------------


class SQLCodegenCollectionAggregateTestCase(SQLCodegenBaseTestCase):

    def test_array_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT ARRAY_AGG(book.title) AS names
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["names"], list)
        self.assertCountEqual(row["names"], ["letters-one.txt", "letters-two.txt", "letters-three.txt"])

    def test_array_agg_distinct(self):
        qs = self.transpiler.to_queryset("""
            SELECT ARRAY_AGG(DISTINCT book.status) AS statuses
            FROM book
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["statuses"], list)
        self.assertCountEqual(row["statuses"], ["PUBLISHED", "REJECTED"])

    def test_array_agg_with_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.status, ARRAY_AGG(book.title) AS names
            FROM book
            GROUP BY book.status
            ORDER BY book.status
        """)
        rows = {r["status"]: r["names"] for r in qs}
        self.assertCountEqual(rows["PUBLISHED"], ["letters-one.txt", "letters-two.txt", "letters-three.txt"])
        self.assertCountEqual(rows["REJECTED"], ["memo.txt"])

    def test_array_agg_order_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT ARRAY_AGG(book.title ORDER BY book.title ASC) AS names
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertEqual(row["names"], sorted(["letters-one.txt", "letters-two.txt", "letters-three.txt"]))

    def test_string_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT STRING_AGG(book.status, ', ') AS statuses
            FROM book
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["statuses"], str)
        for status in ("PUBLISHED", "REJECTED"):
            self.assertIn(status, row["statuses"])

    def test_string_agg_with_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.status, STRING_AGG(book.title, ' | ') AS names
            FROM book
            GROUP BY book.status
            ORDER BY book.status
        """)
        rows = {r["status"]: r["names"] for r in qs}
        self.assertIn("letters-one.txt", rows["PUBLISHED"])
        self.assertIn("|", rows["PUBLISHED"])
        self.assertEqual(rows["REJECTED"], "memo.txt")

    def test_json_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT JSON_AGG(book.title) AS names
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["names"], list)
        self.assertCountEqual(row["names"], ["letters-one.txt", "letters-two.txt", "letters-three.txt"])

    def test_jsonb_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT JSONB_AGG(book.title) AS names
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["names"], list)
        self.assertCountEqual(row["names"], ["letters-one.txt", "letters-two.txt", "letters-three.txt"])

    def test_json_object_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT JSON_OBJECT_AGG(book.title, book.print_run) AS doc_credits
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["doc_credits"], dict)
        self.assertEqual(row["doc_credits"]["letters-one.txt"], 2)
        self.assertEqual(row["doc_credits"]["letters-two.txt"], 4)

    def test_jsonb_object_agg_no_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT JSONB_OBJECT_AGG(book.title, book.print_run) AS doc_credits
            FROM book
            WHERE book.status = 'PUBLISHED'
        """)
        row = list(qs)[0]
        self.assertIsInstance(row["doc_credits"], dict)
        self.assertEqual(row["doc_credits"]["letters-one.txt"], 2)

    def test_json_agg_with_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.status, JSON_AGG(book.title) AS names
            FROM book
            GROUP BY book.status
            ORDER BY book.status
        """)
        rows = {r["status"]: r["names"] for r in qs}
        self.assertCountEqual(rows["PUBLISHED"], ["letters-one.txt", "letters-two.txt", "letters-three.txt"])
        self.assertCountEqual(rows["REJECTED"], ["memo.txt"])

    def test_array_agg_rejects_unsupported_function(self):
        from django_safeql.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.transpiler.to_queryset("SELECT ARRAY_AGG(UNKNOWN_FN(book.title)) FROM book")


# ---------------------------------------------------------------------------
# 8. SELECT-specific
# ---------------------------------------------------------------------------


class SQLCodegenSelectTestCase(SQLCodegenBaseTestCase):
    def test_select_star_returns_matching_rows(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_select_star_expands_only_allowed_fields(self):
        schema = make_codegen_schema()
        schema.tables["book"].allowed_fields = {"id", "title", "status"}
        transpiler = SQLToQuerySetTranspiler(schema)

        qs = transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.id = {document_id}
        """.format(document_id=self.d1.id))

        self.assertEqual({"id", "title", "status"}, set(list(qs)[0].keys()))

    def test_select_joined_table_star_expands_only_allowed_fields(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.*
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.id = {document_id}
        """.format(document_id=self.d1.id))

        self.assertEqual({"author__id", "author__name", "author__publisher_id"}, set(list(qs)[0].keys()))

    def test_select_specific_columns(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, book.status
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE book.status = 'PUBLISHED'
            ORDER BY author.id ASC
        """)
        rows = list(qs)
        self.assertEqual(set(rows[0].keys()), {"author__id", "status"})

    def test_select_alias_without_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT LOWER(book.title) AS normalized_name,
                   book.print_run * 2 AS weighted_credits
            FROM book
            WHERE book.title = 'letters-one.txt'
        """)
        self.assertSqlContains(qs, "LOWER", "WEIGHTED_CREDITS")
        self.assertEqual(list(qs), [{"normalized_name": "letters-one.txt", "weighted_credits": 4}])

    def test_select_alias_used_in_order_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.print_run * 2 AS double_credits
            FROM book
            ORDER BY double_credits DESC
        """)
        credits = [row["double_credits"] for row in qs]
        self.assertEqual(credits, sorted(credits, reverse=True))

    def test_select_alias_used_in_having(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            HAVING COUNT(*) >= 2
            ORDER BY total DESC
        """)
        self.assertEqual(list(qs), [{"author__id": self.author_x.id, "total": 2}])

    def test_select_distinct(self):
        qs = self.transpiler.to_queryset("""
            SELECT DISTINCT book.status FROM book ORDER BY book.status ASC
        """)
        self.assertSqlContains(qs, "SELECT DISTINCT")
        self.assertEqual(list(qs), [{"status": "PUBLISHED"}, {"status": "REJECTED"}])

    def test_select_limit(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id ASC LIMIT 1
        """)
        self.assertSqlContains(qs, "LIMIT")
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_select_order_by_desc(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book WHERE book.status = 'PUBLISHED' ORDER BY book.id DESC LIMIT 2
        """)
        self.assertEqual(self.ids(qs), [self.d4.id, self.d2.id])


# ---------------------------------------------------------------------------
# 8. Nested
# ---------------------------------------------------------------------------


class SQLCodegenNestedTestCase(SQLCodegenBaseTestCase):
    def test_arithmetic_inside_aggregate(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, SUM((book.print_run + 1) * 2) AS weighted
            FROM book
            JOIN author ON book.author_id = author.id
            GROUP BY author.id
            ORDER BY author.id ASC
        """)
        by_author = {row["author__id"]: row for row in qs}
        self.assertEqual(by_author[self.author_x.id]["weighted"], (2 + 1) * 2 + (4 + 1) * 2)

    def test_function_in_where_on_joined_column(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE LOWER(author.name) = 'ada lovelace' AND book.status = 'PUBLISHED'
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id, self.d4.id])

    def test_cast_inside_aggregate_having(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id, COUNT(*) AS total
            FROM book
            JOIN author ON book.author_id = author.id
            WHERE (book.metadata->>'total')::numeric > 80
            GROUP BY author.id
            HAVING COUNT(*) >= 1
            ORDER BY total DESC
        """)
        rows = list(qs)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIn("total", row)

    def test_nested_string_functions_in_select(self):
        qs = self.transpiler.to_queryset("""
            SELECT CONCAT(UPPER(SUBSTRING(book.title FROM 1 FOR 7)), '-', book.status) AS label
            FROM book
            WHERE book.title = 'letters-one.txt'
        """)
        self.assertEqual(list(qs)[0]["label"], "LETTERS-PUBLISHED")

    def test_or_inside_and_with_json_and_function(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.*
            FROM book
            JOIN author ON book.author_id = author.id
            JOIN publisher ON author.publisher_id = publisher.id
            WHERE publisher.name = 'Acme'
              AND (book.status = 'REJECTED' OR book.metadata->>'currency' = 'USD')
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d2.id, self.d3.id])

    def test_full_surface(self):
        qs = self.transpiler.to_queryset("""
            SELECT author.id,
                   LOWER(author.name) AS author_name,
                   COUNT(*) AS total,
                   SUM((book.print_run + 1) * 2) AS weighted_credits,
                   AVG(book.print_run) AS average_credits,
                   MIN(book.print_run) AS prints_min,
                   MAX(book.print_run) AS prints_max
            FROM book
            JOIN author ON book.author_id = author.id
            JOIN publisher ON author.publisher_id = publisher.id
            WHERE publisher.name = 'Acme'
              AND book.status IN ('PUBLISHED', 'REJECTED')
              AND book.title ILIKE 'letters-%'
              AND book.metadata ? 'source'
              AND (book.metadata->>'total')::numeric >= 80
            GROUP BY author.id, author.name
            HAVING COUNT(*) >= 2
            ORDER BY total DESC, author_name ASC
            LIMIT 10
        """)
        self.assertSqlContains(qs, "GROUP BY", "HAVING", "LOWER", "COUNT", "SUM", "AVG", "MIN", "MAX", "LIMIT")
        self.assertEqual(
            list(qs),
            [
                {
                    "author__id": self.author_x.id,
                    # GROUP BY author.id, author.name — author.name is a real GROUP BY
                    # key (not just the LOWER() projection of it), so it must appear in
                    # the grouped output alongside author_name, matching the SQL text.
                    "author__name": "Ada Lovelace",
                    "author_name": "ada lovelace",
                    "total": 2,
                    "weighted_credits": (2 + 1) * 2 + (4 + 1) * 2,
                    "average_credits": 3.0,
                    "prints_min": 2,
                    "prints_max": 4,
                }
            ],
        )


# ---------------------------------------------------------------------------
# 9. Date and time functions
# ---------------------------------------------------------------------------


class SQLCodegenDateTimeFunctionTestCase(SQLCodegenBaseTestCase):
    # --- NOW() / CURRENT_TIMESTAMP ---

    def test_now_filter_all_docs_before_now(self):
        qs = self.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.created < NOW()")
        self.assertEqual(list(qs)[0]["total"], 4)

    def test_now_filter_no_docs_after_now(self):
        qs = self.transpiler.to_queryset("SELECT COUNT(*) AS total FROM book WHERE book.created > NOW()")
        self.assertEqual(list(qs)[0]["total"], 0)

    # --- EXTRACT ---

    def test_extract_year_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(YEAR FROM book.created) AS yr FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertEqual(list(qs)[0]["yr"], datetime.datetime.now().year)

    def test_extract_month_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(MONTH FROM book.created) AS mo FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertEqual(list(qs)[0]["mo"], datetime.datetime.now().month)

    def test_extract_day_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(DAY FROM book.created) AS dy FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertEqual(list(qs)[0]["dy"], datetime.datetime.now().day)

    def test_extract_quarter_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(QUARTER FROM book.created) AS q FROM book WHERE book.id = {self.d1.id}"
        )
        expected_quarter = (datetime.datetime.now().month - 1) // 3 + 1
        self.assertEqual(list(qs)[0]["q"], expected_quarter)

    def test_extract_week_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(WEEK FROM book.created) AS wk FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["wk"])

    def test_extract_hour_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(HOUR FROM book.created) AS hr FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["hr"])

    def test_extract_minute_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(MINUTE FROM book.created) AS mn FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["mn"])

    def test_extract_second_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT EXTRACT(SECOND FROM book.created) AS sc FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["sc"])

    def test_extract_all_parts_in_one_select(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT EXTRACT(YEAR FROM book.created) AS yr,
                   EXTRACT(QUARTER FROM book.created) AS q,
                   EXTRACT(MONTH FROM book.created) AS mo,
                   EXTRACT(WEEK FROM book.created) AS wk,
                   EXTRACT(DAY FROM book.created) AS dy,
                   EXTRACT(HOUR FROM book.created) AS hr,
                   EXTRACT(MINUTE FROM book.created) AS mn,
                   EXTRACT(SECOND FROM book.created) AS sc
            FROM book WHERE book.id = {self.d1.id}
        """)
        row = list(qs)[0]
        now = datetime.datetime.now()
        self.assertEqual(row["yr"], now.year)
        self.assertEqual(row["mo"], now.month)
        self.assertEqual(row["dy"], now.day)

    def test_extract_year_in_where(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT COUNT(*) AS total FROM book
            WHERE EXTRACT(YEAR FROM book.created) = {datetime.datetime.now().year}
        """)
        self.assertEqual(list(qs)[0]["total"], 4)

    # --- date_trunc ---

    def test_trunc_year_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('year', book.created) AS yr FROM book WHERE book.id = {self.d1.id}"
        )
        row = list(qs)[0]
        self.assertIsInstance(row["yr"], (datetime.datetime, datetime.date))

    def test_trunc_quarter_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('quarter', book.created) AS q FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["q"])

    def test_trunc_month_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('month', book.created) AS mo FROM book WHERE book.id = {self.d1.id}"
        )
        row = list(qs)[0]
        self.assertIsInstance(row["mo"], (datetime.datetime, datetime.date))

    def test_trunc_week_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('week', book.created) AS wk FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["wk"])

    def test_trunc_day_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('day', book.created) AS dy FROM book WHERE book.id = {self.d1.id}"
        )
        row = list(qs)[0]
        self.assertIsInstance(row["dy"], (datetime.datetime, datetime.date))

    def test_trunc_hour_in_select(self):
        qs = self.transpiler.to_queryset(
            f"SELECT date_trunc('hour', book.created) AS hr FROM book WHERE book.id = {self.d1.id}"
        )
        self.assertIsNotNone(list(qs)[0]["hr"])

    def test_trunc_month_in_where_matches_all_docs(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total FROM book
            WHERE date_trunc('month', book.created) = date_trunc('month', NOW())
        """)
        self.assertEqual(list(qs)[0]["total"], 4)

    def test_trunc_year_in_where_matches_all_docs(self):
        qs = self.transpiler.to_queryset("""
            SELECT COUNT(*) AS total FROM book
            WHERE date_trunc('year', book.created) = date_trunc('year', NOW())
        """)
        self.assertEqual(list(qs)[0]["total"], 4)

    # --- GROUP BY with date functions ---

    def test_extract_year_group_by_single_bucket(self):
        qs = self.transpiler.to_queryset("""
            SELECT EXTRACT(YEAR FROM book.created) AS yr, COUNT(*) AS total
            FROM book
            GROUP BY yr
            ORDER BY yr ASC
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 4)

    def test_extract_month_group_by_single_bucket(self):
        qs = self.transpiler.to_queryset("""
            SELECT EXTRACT(YEAR FROM book.created) AS yr,
                   EXTRACT(MONTH FROM book.created) AS mo,
                   COUNT(*) AS total
            FROM book
            GROUP BY yr, mo
            ORDER BY yr, mo
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 4)

    def test_trunc_month_group_by_single_bucket(self):
        qs = self.transpiler.to_queryset("""
            SELECT date_trunc('month', book.created) AS period, COUNT(*) AS total
            FROM book
            GROUP BY period
            ORDER BY period ASC
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 4)

    # --- Combinations ---

    def test_extract_in_aggregate_having(self):
        qs = self.transpiler.to_queryset("""
            SELECT EXTRACT(YEAR FROM book.created) AS yr, COUNT(*) AS total
            FROM book
            GROUP BY yr
            HAVING COUNT(*) > 0
            ORDER BY yr ASC
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)

    def test_trunc_and_extract_combined(self):
        qs = self.transpiler.to_queryset("""
            SELECT date_trunc('month', book.created) AS period,
                   EXTRACT(MONTH FROM book.created) AS mo,
                   COUNT(*) AS total
            FROM book
            WHERE book.created < NOW()
            GROUP BY period, mo
            ORDER BY period ASC
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total"], 4)


# ---------------------------------------------------------------------------
# 10. jsonb_array_length
# ---------------------------------------------------------------------------


class SQLCodegenJsonbArrayLengthTestCase(SQLCodegenBaseTestCase):
    def test_jsonb_array_length_in_select(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_array_length(book.metadata->'lines') AS line_count
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["line_count"], 2)

    def test_jsonb_array_length_empty_array(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_array_length(book.metadata->'lines') AS line_count
            FROM book WHERE book.id = {self.d2.id}
        """)
        self.assertEqual(list(qs)[0]["line_count"], 0)

    def test_jsonb_array_length_in_where_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_array_length(book.metadata->'lines') > 0
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_jsonb_array_length_in_where_equals(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_array_length(book.metadata->'lines') = 2
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_jsonb_array_length_in_aggregate(self):
        qs = self.transpiler.to_queryset("""
            SELECT SUM(jsonb_array_length(book.metadata->'lines')) AS total_lines
            FROM book
            WHERE book.metadata ? 'lines'
        """)
        self.assertEqual(list(qs)[0]["total_lines"], 2)

    def test_jsonb_array_length_group_by(self):
        qs = self.transpiler.to_queryset("""
            SELECT jsonb_array_length(book.metadata->'lines') AS line_count,
                   COUNT(*) AS total
            FROM book
            WHERE book.metadata ? 'lines'
            GROUP BY line_count
            ORDER BY line_count ASC
        """)
        rows = list(qs)
        by_count = {r["line_count"]: r["total"] for r in rows}
        self.assertEqual(by_count[0], 1)
        self.assertEqual(by_count[2], 1)

    # --- unqualified column (SQLGlot Lambda bug path) ---

    def test_jsonb_array_length_unqualified_in_select(self):
        # SQLGlot parses unqualified col->'key' as Lambda inside Anonymous fn calls.
        # visit_Lambda must convert it back to JsonPath.
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_array_length(metadata->'lines') AS line_count
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["line_count"], 2)

    def test_jsonb_array_length_unqualified_in_where(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_array_length(metadata->'lines') > 0
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id])

    def test_jsonb_array_length_unqualified_in_aggregate(self):
        qs = self.transpiler.to_queryset("""
            SELECT SUM(jsonb_array_length(metadata->'lines')) AS total_lines
            FROM book
            WHERE book.metadata ? 'lines'
        """)
        self.assertEqual(list(qs)[0]["total_lines"], 2)

    def test_jsonb_array_length_unqualified_chained_path(self):
        # Chained: col->'a'->'b' — Lambda body is JSONExtract, not a simple Literal.
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_array_length(metadata->'lines') AS line_count
            FROM book WHERE book.id = {self.d2.id}
        """)
        self.assertEqual(list(qs)[0]["line_count"], 0)

    def test_jsonb_typeof_unqualified(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_typeof(metadata->'lines') AS t
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["t"], "array")


# ---------------------------------------------------------------------------
# 11. JSON scalar functions
# ---------------------------------------------------------------------------


class SQLCodegenJsonFunctionsTestCase(SQLCodegenBaseTestCase):

    # --- jsonb_typeof ---

    def test_jsonb_typeof_array(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_typeof(book.metadata->'lines') AS t
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["t"], "array")

    def test_jsonb_typeof_string(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_typeof(book.metadata->'currency') AS t
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["t"], "string")

    def test_jsonb_typeof_in_where(self):
        # Only d1 and d2 have a 'lines' field whose typeof is 'array'
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_typeof(book.metadata->'lines') = 'array'
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id])

    # --- jsonb_extract_path ---

    def test_jsonb_extract_path_single_key(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_extract_path(book.metadata, 'currency') AS val
            FROM book WHERE book.id = {self.d1.id}
        """)
        # jsonb_extract_path returns jsonb; Django deserializes it → Python string
        self.assertEqual(list(qs)[0]["val"], "EUR")

    def test_jsonb_extract_path_nested(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_extract_path(book.metadata, 'lines', '0') AS first_line
            FROM book WHERE book.id = {self.d1.id}
        """)
        row = list(qs)[0]
        self.assertIsNotNone(row["first_line"])
        # jsonb_extract_path returns jsonb; Django deserializes object → dict
        result = row["first_line"]
        if isinstance(result, str):
            import json as _json

            result = _json.loads(result)
        self.assertEqual(result["label"], "A")

    # --- jsonb_extract_path_text ---

    def test_jsonb_extract_path_text_single_key(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_extract_path_text(book.metadata, 'currency') AS val
            FROM book WHERE book.id = {self.d1.id}
        """)
        # _text variant returns plain text without JSON quotes
        self.assertEqual(list(qs)[0]["val"], "EUR")

    def test_jsonb_extract_path_text_in_where(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_extract_path_text(book.metadata, 'currency') = 'USD'
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d2.id])

    def test_jsonb_extract_path_text_nested(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_extract_path_text(book.metadata, 'lines', '0', 'label') AS lbl
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertEqual(list(qs)[0]["lbl"], "A")

    # --- jsonb_strip_nulls ---

    def test_jsonb_strip_nulls_removes_null_fields(self):
        from tests.testapp.models import Book

        doc = Book.objects.create(
            author=self.author_x,
            status="PUBLISHED",
            title="null-test.txt",
            print_run=1,
            metadata={"currency": "EUR", "ref": None, "total": "10.00"},
        )
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_strip_nulls(book.metadata) AS clean
            FROM book WHERE book.id = {doc.id}
        """)
        result = list(qs)[0]["clean"]
        self.assertNotIn("ref", result)
        self.assertIn("currency", result)

    def test_jsonb_strip_nulls_no_nulls_unchanged(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_strip_nulls(book.metadata) AS clean
            FROM book WHERE book.id = {self.d1.id}
        """)
        result = list(qs)[0]["clean"]
        self.assertEqual(result["currency"], "EUR")

    # --- jsonb_pretty ---

    def test_jsonb_pretty_returns_indented_text(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_pretty(book.metadata) AS pretty
            FROM book WHERE book.id = {self.d1.id}
        """)
        pretty = list(qs)[0]["pretty"]
        self.assertIsInstance(pretty, str)
        self.assertIn("\n", pretty)
        self.assertIn("EUR", pretty)

    # --- jsonb_path_exists ---

    def test_jsonb_path_exists_true(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_path_exists(book.metadata, '$.lines') AS has_lines
            FROM book WHERE book.id = {self.d1.id}
        """)
        self.assertTrue(list(qs)[0]["has_lines"])

    def test_jsonb_path_exists_false(self):
        # d3 has no 'lines' key
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_path_exists(book.metadata, '$.lines') AS has_lines
            FROM book WHERE book.id = {self.d3.id}
        """)
        self.assertFalse(list(qs)[0]["has_lines"])

    def test_jsonb_path_exists_in_where(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.* FROM book
            WHERE jsonb_path_exists(book.metadata, '$.lines') = TRUE
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d1.id, self.d2.id])

    # --- jsonb_path_query_first ---

    def test_jsonb_path_query_first_returns_value(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_path_query_first(book.metadata, '$.lines[0]') AS first_line
            FROM book WHERE book.id = {self.d1.id}
        """)
        result = list(qs)[0]["first_line"]
        # Django deserializes jsonb object → dict
        if isinstance(result, str):
            import json as _json

            result = _json.loads(result)
        self.assertEqual(result["label"], "A")

    def test_jsonb_path_query_first_empty_array_returns_null(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_path_query_first(book.metadata, '$.lines[0]') AS first_line
            FROM book WHERE book.id = {self.d2.id}
        """)
        self.assertIsNone(list(qs)[0]["first_line"])

    def test_jsonb_path_query_first_scalar_value(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT jsonb_path_query_first(book.metadata, '$.currency') AS cur
            FROM book WHERE book.id = {self.d1.id}
        """)
        # Django deserializes jsonb string → Python string
        self.assertEqual(list(qs)[0]["cur"], "EUR")


# ---------------------------------------------------------------------------
# 12. award join
# ---------------------------------------------------------------------------


class SQLCodegenAwardTestCase(SQLCodegenBaseTestCase):
    """Tests for joining through book → author → award_set."""

    def setUp(self):
        super().setUp()
        # Mark one award official, add another that is not featured
        Award.objects.filter(author=self.author_x, name="total").update(is_official=True)
        Award.objects.create(
            author=self.author_x,
            name="genre",
            category="ONELINE",
            is_official=False,
            is_featured=False,
        )

    def test_award_distinct_names(self):
        # author_x has 3 fields; filter by author to exclude NULLs from parsers without fields
        qs = self.transpiler.to_queryset(f"""
            SELECT DISTINCT award.name FROM book
            WHERE book.author_id = {self.author_x.id}
            ORDER BY award.name ASC
        """)
        names = [r["author__award_set__name"] for r in list(qs)]
        self.assertEqual(names, ["currency", "genre", "total"])

    def test_award_category_list(self):
        qs = self.transpiler.to_queryset("""
            SELECT DISTINCT award.name AS fname, award.category AS fmt
            FROM book
            WHERE book.status = 'PUBLISHED'
            ORDER BY award.name ASC
        """)
        rows = list(qs)
        by_name = {r["fname"]: r["fmt"] for r in rows}
        self.assertEqual(by_name["total"], "TEXT")
        self.assertEqual(by_name["currency"], "TEXT")
        self.assertEqual(by_name["genre"], "ONELINE")

    def test_award_official_filter(self):
        qs = self.transpiler.to_queryset("""
            SELECT DISTINCT award.name AS fname FROM book
            WHERE award.is_official = TRUE
            ORDER BY award.name ASC
        """)
        names = [r["fname"] for r in list(qs)]
        self.assertEqual(names, ["total"])

    def test_award_not_featured(self):
        qs = self.transpiler.to_queryset("""
            SELECT DISTINCT award.name AS fname FROM book
            WHERE award.is_featured = FALSE
            ORDER BY award.name ASC
        """)
        names = [r["fname"] for r in list(qs)]
        self.assertEqual(names, ["genre"])

    def test_award_count(self):
        # 3 awards × 2 PUBLISHED docs = 6 rows → GROUP BY field gives 3 buckets each with 2
        qs = self.transpiler.to_queryset("""
            SELECT award.name AS fname, COUNT(*) AS doc_count
            FROM book
            WHERE book.status = 'PUBLISHED' AND book.author_id = {}
            GROUP BY fname
            ORDER BY fname ASC
        """.format(self.author_x.id))
        rows = list(qs)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["doc_count"] == 2 for r in rows))

    def test_award_author_id_matches(self):
        qs = self.transpiler.to_queryset(f"""
            SELECT DISTINCT award.author_id AS pid FROM book
            WHERE book.author_id = {self.author_x.id}
              AND award.author_id IS NOT NULL
        """)
        pids = {r["pid"] for r in list(qs)}
        self.assertIn(self.author_x.id, pids)
        self.assertNotIn(self.author_y.id, pids)
        self.assertNotIn(self.author_z.id, pids)


# ---------------------------------------------------------------------------
# Lateral joins and EXISTS
# ---------------------------------------------------------------------------


class SQLCodegenLateralJoinTestCase(SQLCodegenBaseTestCase):

    def test_left_join_lateral_annotates_author_name(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
            ) AS pinfo ON true
            ORDER BY book.id ASC
        """)
        rows = {r["id"]: r["author_name"] for r in list(qs)}
        self.assertEqual(rows[self.d1.id], "Ada Lovelace")
        self.assertEqual(rows[self.d2.id], "Ada Lovelace")
        self.assertEqual(rows[self.d3.id], "Charles Babbage")
        self.assertEqual(rows[self.d4.id], "Ada Lovelace")

    def test_left_join_lateral_uses_subquery_not_raw_sql(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p WHERE p.id = book.author_id LIMIT 1
            ) AS pinfo ON true
        """)
        sql, _ = qs.query.sql_with_params()
        self.assertIn("SELECT", sql.upper())
        self.assertNotIn("LATERAL", sql.upper())

    def test_cross_join_lateral_acts_as_inner_join(self):
        # The inner WHERE restricts to author name 'Charles Babbage', so only d3 survives
        # the CROSS JOIN LATERAL isnull filter.
        qs = self.transpiler.to_queryset("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            CROSS JOIN LATERAL (
                SELECT p.name FROM author p
                WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
                LIMIT 1
            ) AS pinfo
            ORDER BY book.id ASC
        """)
        rows = list(qs)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.d3.id)
        self.assertEqual(rows[0]["author_name"], "Charles Babbage")

    def test_exists_in_where_filters_by_author_name(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id FROM book
            WHERE EXISTS (
                SELECT 1 FROM author p
                WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
            )
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), [self.d3.id])

    def test_not_exists_in_where(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id FROM book
            WHERE NOT EXISTS (
                SELECT 1 FROM author p
                WHERE p.id = book.author_id AND p.name = 'Charles Babbage'
            )
            ORDER BY book.id ASC
        """)
        self.assertEqual(self.ids(qs), sorted([self.d1.id, self.d2.id, self.d4.id]))

    def test_jsonb_array_elements_sum_per_document(self):
        # d1 has lines=[{amount:"100.50"}, {amount:"20.00"}], d2 has lines=[]
        qs = self.transpiler.to_queryset("""
            SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            GROUP BY book.id
            ORDER BY book.id ASC
        """)
        rows = {r["id"]: r["total_amount"] for r in list(qs)}
        self.assertIn(self.d1.id, rows)
        # d1: 100.50 + 20.00 = 120.50
        self.assertAlmostEqual(float(rows[self.d1.id]), 120.50, places=2)
        # d2: empty lines array → SUM returns NULL
        self.assertIsNone(rows[self.d2.id])

    def test_jsonb_array_elements_uses_correlated_subquery(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            GROUP BY book.id
        """)
        sql, _ = qs.query.sql_with_params()
        self.assertIn("jsonb_array_elements", sql.lower())
        self.assertNotIn("LATERAL", sql.upper())

    def test_jsonb_array_elements_whole_table_aggregate(self):
        # SUM across all documents: only d1 has non-empty lines (120.50)
        result = self.transpiler.to_queryset("""
            SELECT SUM((item->>'amount')::numeric) AS grand_total
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
        """)
        rows = list(result)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["grand_total"] or 0), 120.50, places=2)

    def test_jsonb_array_elements_element_key_is_bound_parameter(self):
        # The JSON key ('amount') must be sent to the database as a bound parameter,
        # never interpolated into the SQL text.
        qs = self.transpiler.to_queryset("""
            SELECT book.id, SUM((item->>'amount')::numeric) AS total_amount
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            GROUP BY book.id
        """)
        sql, params = qs.query.sql_with_params()
        self.assertIn("elem->>%s", sql)
        self.assertNotIn("->>'amount'", sql)
        self.assertIn("amount", params)

    def test_jsonb_array_elements_key_with_apostrophe(self):
        # A JSON key containing a single quote must round-trip correctly instead of
        # breaking the generated SQL — regression test for the raw-interpolation bug.
        book = Book.objects.create(
            author=self.author_x,
            status="PUBLISHED",
            title="apostrophe.txt",
            metadata={"lines": [{"o'clock": "42.00"}]},
        )
        qs = self.transpiler.to_queryset(f"""
            SELECT book.id, SUM((item->>'o''clock')::numeric) AS total_amount
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            WHERE book.id = {book.id}
            GROUP BY book.id
        """)
        rows = {r["id"]: r["total_amount"] for r in list(qs)}
        self.assertAlmostEqual(float(rows[book.id]), 42.00, places=2)

    def test_jsonb_array_elements_element_key_injection_is_neutralized(self):
        # Regression test for the SQL injection via the LATERAL jsonb_array_elements
        # element key (see audit): a malicious key must never break out of the
        # generated SQL, and must never appear in the SQL text — only in params.
        qs = self.transpiler.to_queryset("""
            SELECT book.id, SUM((item->>'x'') UNION SELECT password FROM auth_user --')::numeric) AS total
            FROM book
            LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true
            GROUP BY book.id
        """)
        sql, params = qs.query.sql_with_params()
        self.assertNotIn("UNION", sql.upper())
        self.assertNotIn("auth_user", sql)
        self.assertIn("x') UNION SELECT password FROM auth_user --", params)
        # Executing must not raise a SQL syntax error — the payload is bound as an
        # inert literal key that simply matches nothing.
        list(qs)

    def test_lateral_inner_where_in_values(self):
        qs = self.transpiler.to_queryset("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p
                WHERE p.id = book.author_id
                  AND p.name IN ('Ada Lovelace', 'Charles Babbage')
                LIMIT 1
            ) AS pinfo ON true
            ORDER BY book.id ASC
        """)
        rows = {r["id"]: r["author_name"] for r in list(qs)}
        self.assertEqual(rows[self.d1.id], "Ada Lovelace")
        self.assertEqual(rows[self.d3.id], "Charles Babbage")

    def test_lateral_correlated_with_not_condition(self):
        # _find_correlated_field must traverse Not nodes
        qs = self.transpiler.to_queryset("""
            SELECT book.id, pinfo.name AS author_name
            FROM book
            LEFT JOIN LATERAL (
                SELECT p.name FROM author p
                WHERE p.id = book.author_id AND NOT p.name = 'Charles Babbage'
                LIMIT 1
            ) AS pinfo ON true
            ORDER BY book.id ASC
        """)
        rows = {r["id"]: r["author_name"] for r in list(qs)}
        self.assertIsNone(rows.get(self.d3.id))
        self.assertEqual(rows[self.d1.id], "Ada Lovelace")
