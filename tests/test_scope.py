import pytest

from django_safeql.nodes import Column
from django_safeql.scope import ScopeStack


def test_resolves_inner_value_first_then_outer_value():
    scope = ScopeStack()
    root, child = object(), object()

    with scope.scoped(root, alias_to_table={"book": "book"}):
        assert scope.get("alias_to_table") == {"book": "book"}
        with scope.scoped(child, alias_to_table={"d": "book"}):
            assert scope.get("alias_to_table") == {"d": "book"}
        assert scope.get("alias_to_table") == {"book": "book"}


def test_mutates_current_frame_mapping():
    scope = ScopeStack()

    with scope.scoped(object(), select_aliases={}):
        aliases = scope.mutate_mapping("select_aliases")
        aliases["total"] = Column(name="id")
        assert "total" in scope.get("select_aliases")


def test_detects_mismatched_pop():
    scope = ScopeStack()
    scope.push(object())

    with pytest.raises(RuntimeError):
        scope.pop(object())
