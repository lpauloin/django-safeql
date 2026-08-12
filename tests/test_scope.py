from django.test import TestCase

from django_safeql.nodes import Column
from django_safeql.scope import ScopeStack


class ScopeStackTestCase(TestCase):
    def test_scope_resolves_inner_value_first_then_outer_value(self):
        scope = ScopeStack()
        root = object()
        child = object()

        with scope.scoped(root, alias_to_table={"book": "book"}):
            assert scope.get("alias_to_table") == {"book": "book"}
            with scope.scoped(child, alias_to_table={"d": "book"}):
                assert scope.get("alias_to_table") == {"d": "book"}
            assert scope.get("alias_to_table") == {"book": "book"}

    def test_scope_mutates_current_frame_mapping(self):
        scope = ScopeStack()
        node = object()

        with scope.scoped(node, select_aliases={}):
            aliases = scope.mutate_mapping("select_aliases")
            aliases["total"] = Column(name="id")
            assert "total" in scope.get("select_aliases")

    def test_scope_detects_mismatched_pop(self):
        scope = ScopeStack()
        root = object()
        other = object()
        scope.push(root)

        with self.assertRaises(RuntimeError):
            scope.pop(other)
