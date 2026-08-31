import pytest
from django.db import connection

from django_safeql.exceptions import ValidationError
from django_safeql.targets import MYSQL, POSTGRESQL, SQLITE, Feature, resolve_target
from django_safeql.transpiler import SQLToQuerySetTranspiler
from tests.schema_factory import make_schema

ALL_TARGETS = [POSTGRESQL, SQLITE, MYSQL]

# One representative query per gated feature. The matrix test below runs each against
# every target and asserts it is accepted exactly when the target declares the feature —
# so every capability is exercised on every backend. `test_every_feature_has_a_query`
# guarantees this table stays complete as features are added or removed.
FEATURE_QUERIES = [
    (Feature.JSON_CONTAINS, 'SELECT book.* FROM book WHERE book.metadata @> \'{"source": "email"}\''),
    (Feature.ARRAY_AGG_MODIFIERS, "SELECT ARRAY_AGG(DISTINCT book.title) AS n FROM book"),
    (Feature.JSONB_SCALAR_FUNCTIONS, "SELECT jsonb_typeof(book.metadata->'lines') AS t FROM book"),
    (Feature.JSONPATH, "SELECT jsonb_path_exists(book.metadata, '$.source') AS ok FROM book"),
    (
        Feature.LATERAL_SRF,
        "SELECT book.id, SUM((item->>'amount')::numeric) AS total FROM book "
        "LEFT JOIN LATERAL jsonb_array_elements(book.metadata->'lines') AS item ON true GROUP BY book.id",
    ),
]


def test_resolve_target_by_name():
    assert resolve_target("sqlite") is SQLITE


def test_resolve_target_passes_through_a_target_instance():
    assert resolve_target(POSTGRESQL) is POSTGRESQL


def test_resolve_unknown_target_raises():
    with pytest.raises(ValueError, match="Unknown target"):
        resolve_target("oracle")


def test_target_matching_the_connection_vendor_builds_a_queryset():
    transpiler = SQLToQuerySetTranspiler(make_schema(), target=connection.vendor)
    assert transpiler.to_queryset("SELECT book.* FROM book") is not None


def test_target_that_disagrees_with_the_connection_vendor_is_rejected():
    # Declaring a target that does not match the database the queryset runs on is a
    # configuration mismatch and must fail before any SQL is generated.
    wrong_target = "sqlite" if connection.vendor != "sqlite" else "postgresql"
    transpiler = SQLToQuerySetTranspiler(make_schema(), target=wrong_target)
    with pytest.raises(ValueError, match="does not match"):
        transpiler.to_queryset("SELECT book.* FROM book")


def test_every_feature_has_a_query():
    # Every declared capability must appear in the matrix, so no feature ships untested.
    declared = {value for name, value in vars(Feature).items() if not name.startswith("_") and isinstance(value, str)}
    covered = {feature for feature, _ in FEATURE_QUERIES}
    assert covered == declared


@pytest.mark.parametrize("target", ALL_TARGETS, ids=lambda t: t.name)
@pytest.mark.parametrize("feature, sql", FEATURE_QUERIES, ids=[feature for feature, _ in FEATURE_QUERIES])
def test_feature_is_gated_exactly_by_its_capability(feature, sql, target):
    # Accepted iff the target declares the feature; otherwise rejected with a message
    # naming the target — the accept/reject contract for every capability × backend.
    transpiler = SQLToQuerySetTranspiler(make_schema(), target=target)
    if target.supports(feature):
        assert transpiler.to_ast(sql) is not None
    else:
        with pytest.raises(ValidationError, match=f"{target.name} target"):
            transpiler.to_ast(sql)


def test_json_contains_is_allowed_on_mysql_but_not_sqlite():
    # @> is the one gated feature MySQL supports (via Django's __contains lookup) while
    # SQLite does not, so the two restricted targets must not behave identically.
    sql = 'SELECT book.* FROM book WHERE book.metadata @> \'{"source": "email"}\''
    SQLToQuerySetTranspiler(make_schema(), target="mysql").to_ast(sql)
    with pytest.raises(ValidationError, match="sqlite target"):
        SQLToQuerySetTranspiler(make_schema(), target="sqlite").to_ast(sql)


def test_array_agg_modifiers_are_allowed_on_sqlite_but_not_mysql():
    # SQLite's json_group_array carries DISTINCT / ORDER BY; MySQL's JSON_ARRAYAGG does not.
    sql = "SELECT ARRAY_AGG(DISTINCT book.title) AS names FROM book"
    SQLToQuerySetTranspiler(make_schema(), target="sqlite").to_ast(sql)
    with pytest.raises(ValidationError, match="mysql target"):
        SQLToQuerySetTranspiler(make_schema(), target="mysql").to_ast(sql)
