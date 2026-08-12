class JsonSchemaResolver:
    def resolve_path(self, schema, path):
        current = schema
        for part in path:
            current = self._resolve_part(current, part)
            if current is None:
                return None
        return current

    def _resolve_part(self, schema, part):
        # anyOf/oneOf/allOf: the part may be defined in any branch — return the
        # first branch that resolves it.
        for key in ("anyOf", "oneOf", "allOf"):
            if key in schema:
                for candidate in schema[key]:
                    resolved = self._resolve_part(candidate, part)
                    if resolved is not None:
                        return resolved
                return None

        current_type = self._main_type(schema)
        if current_type == "object":
            return schema.get("properties", {}).get(str(part))
        if current_type == "array":
            item_schema = schema.get("items")
            if item_schema is None:
                return None
            if isinstance(part, int):
                return item_schema
            if self._main_type(item_schema) == "object":
                return item_schema.get("properties", {}).get(str(part))
        return None

    def _main_type(self, schema):
        type_ = schema.get("type")
        if isinstance(type_, list):
            for item in type_:
                if item != "null":
                    return item
            return "null"
        return type_


def json_schema_type(schema):
    if not schema:
        return "unknown"
    type_ = schema.get("type", "unknown")
    if isinstance(type_, list):
        for item in type_:
            if item != "null":
                return item
        return "null"
    return type_
