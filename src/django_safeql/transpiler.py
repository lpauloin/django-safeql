from django.db import connections

from django_safeql.annotation import AnnotationVisitor
from django_safeql.ast import SQLGlotParser
from django_safeql.codegen import CodegenVisitor
from django_safeql.exceptions import UnsupportedSQL
from django_safeql.targets import resolve_target
from django_safeql.validation import ValidationVisitor


class SQLToQuerySetTranspiler:
    def __init__(self, schema, target="postgresql"):
        self.schema = schema
        self.target = resolve_target(target)
        self.parser = SQLGlotParser()

    def parse(self, sql):
        return self.parser.parse(sql)

    def annotate(self, ast):
        return AnnotationVisitor(self.schema).visit(ast)

    def validate(self, ast):
        return ValidationVisitor(self.schema, self.target).visit(ast)

    def codegen(self, ast):
        return CodegenVisitor(self.target).visit(ast)

    def to_queryset(self, sql):
        # The declared target must match the database the queryset will run on, or the
        # generated SQL would be wrong for the backend that executes it.
        connection_vendor = connections[self.schema.base_queryset.db].vendor
        if connection_vendor != self.target.vendor:
            raise ValueError(
                f"Target {self.target.name!r} does not match the base queryset's "
                f"database (vendor {connection_vendor!r}); pass the matching target."
            )
        # A deeply nested query can exhaust the interpreter stack in the parser or a
        # visitor; turn that into the library's normal "unsupported" signal so callers
        # never see a raw RecursionError.
        try:
            return self.codegen(self.to_ast(sql))
        except RecursionError:
            raise UnsupportedSQL("Query is too deeply nested to process") from None

    def to_ast(self, sql):
        try:
            ast = self.parse(sql)
            self.annotate(ast)
            self.validate(ast)
            return ast
        except RecursionError:
            raise UnsupportedSQL("Query is too deeply nested to process") from None
