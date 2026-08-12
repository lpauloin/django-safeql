from dataclasses import dataclass, field as dataclass_field

from django.db.models import QuerySet


@dataclass
class JsonFieldSchema:
    schema: dict
    strict: bool = True
    allow_unknown_paths: bool = False


@dataclass
class TableSchema:
    queryset: QuerySet
    relation: str = ""
    json_fields: dict[str, JsonFieldSchema] = dataclass_field(default_factory=dict)
    allowed_fields: set[str] | None = None

    @property
    def model(self):
        return self.queryset.model


@dataclass
class SQLTranspilerSchema:
    base_table: str
    base_queryset: QuerySet
    tables: dict[str, TableSchema]
    max_limit: int | None = 1000

    @property
    def base_model(self):
        return self.base_queryset.model

    def get_table(self, table: str) -> TableSchema | None:
        return self.tables.get(table)
