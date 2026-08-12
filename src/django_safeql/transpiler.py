from django_safeql.annotation import AnnotationVisitor
from django_safeql.ast import SQLGlotParser
from django_safeql.codegen import CodegenVisitor
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
        ast = self.to_ast(sql)
        return self.codegen(ast)

    def to_ast(self, sql):
        ast = self.parse(sql)
        self.annotate(ast)
        self.validate(ast)
        return ast
