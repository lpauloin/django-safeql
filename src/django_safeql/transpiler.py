from django_safeql.annotation import AnnotationVisitor
from django_safeql.ast import SQLGlotParser
from django_safeql.codegen import CodegenVisitor
from django_safeql.exceptions import UnsupportedSQL
from django_safeql.validation import ValidationVisitor


class SQLToQuerySetTranspiler:
    def __init__(self, schema):
        self.schema = schema
        self.parser = SQLGlotParser()

    def parse(self, sql):
        return self.parser.parse(sql)

    def annotate(self, ast):
        return AnnotationVisitor(self.schema).visit(ast)

    def validate(self, ast):
        return ValidationVisitor(self.schema).visit(ast)

    def codegen(self, ast):
        return CodegenVisitor().visit(ast)

    def to_queryset(self, sql):
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
