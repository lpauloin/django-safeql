from django_safeql import JsonFieldSchema, SQLTranspilerSchema, TableSchema
from tests.testapp.models import Author, Award, Book, Publisher

METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "priority": {"type": "integer"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "currency": {"type": "string", "enum": ["EUR", "USD"]},
        "total": {"type": "string"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "amount": {"type": "string"},
                },
            },
        },
    },
}

DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "edition": {"type": "integer"},
        "summary": {
            "type": "object",
            "properties": {
                "total": {"type": "number", "description": "Total amount"},
            },
        },
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "amount": {"type": "number"},
                },
            },
        },
    },
}


def make_schema():
    """Schema for annotation/validation tests — virtual fields, no real DB execution."""
    return SQLTranspilerSchema(
        base_table="book",
        base_queryset=Book.objects.all(),
        tables={
            "book": TableSchema(
                queryset=Book.objects.all(),
                relation="",
                allowed_fields={
                    "id",
                    "title",
                    "isbn",
                    "status",
                    "author_id",
                    "publisher_id",
                    "pages",
                    "price",
                    "created",
                    "published_at",
                    "metadata",
                    "details",
                },
                json_fields={
                    "metadata": JsonFieldSchema(schema=METADATA_SCHEMA),
                    "details": JsonFieldSchema(schema=DETAILS_SCHEMA),
                },
            ),
            "publisher": TableSchema(
                queryset=Publisher.objects.all(),
                relation="publisher",
                allowed_fields={"id", "name", "is_active", "uuid"},
            ),
            "author": TableSchema(
                queryset=Author.objects.all(),
                relation="author",
                allowed_fields={"id", "name", "publisher_id"},
            ),
            "award": TableSchema(
                queryset=Award.objects.all(),
                relation="author__award_set",
                allowed_fields={"id", "name", "author_id", "year", "category", "is_official", "is_featured"},
            ),
        },
    )


def make_codegen_schema():
    """Schema for code-generation tests — real model fields and ORM relations."""
    return SQLTranspilerSchema(
        base_table="book",
        base_queryset=Book.objects.all(),
        tables={
            "book": TableSchema(
                queryset=Book.objects.all(),
                relation="",
                json_fields={
                    "metadata": JsonFieldSchema(schema=METADATA_SCHEMA),
                    "details": JsonFieldSchema(schema=DETAILS_SCHEMA),
                },
            ),
            "publisher": TableSchema(
                queryset=Publisher.objects.all(),
                relation="author__publisher",
                allowed_fields={"id", "name"},
            ),
            "author": TableSchema(
                queryset=Author.objects.all(),
                relation="author",
                allowed_fields={"id", "name", "publisher_id"},
            ),
            "award": TableSchema(
                queryset=Award.objects.all(),
                relation="author__award_set",
                allowed_fields={"id", "name", "author_id", "year", "category", "is_official", "is_featured"},
            ),
        },
    )
