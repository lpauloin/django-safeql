def test_select_aliases_are_registered_on_query(transpiler):
    ast = transpiler.to_ast("""
        SELECT LOWER(book.title) AS normalized_title,
               book.pages * 2 AS weighted_pages
        FROM book
        ORDER BY normalized_title ASC
    """)
    aliases = ast.annotations["select_aliases"]
    assert set(aliases) == {"normalized_title", "weighted_pages"}
    assert ast.order_by[0].expression.annotations["select_alias"] == "normalized_title"
    assert ast.order_by[0].expression.annotations["django_path"] == "normalized_title"


def test_group_by_and_having_aggregate_alias(transpiler):
    ast = transpiler.to_ast("""
        SELECT author.id, COUNT(*) AS total
        FROM book
        JOIN author ON book.author_id = author.id
        GROUP BY author.id
        HAVING COUNT(*) >= 1
        ORDER BY total DESC
    """)
    assert ast.group_by[0].annotations["django_path"] == "author__id"
    assert ast.select.columns[1].annotations["alias"] == "total"
    assert ast.having.left.annotations["aggregate_function"] == "count"
    assert ast.order_by[0].expression.annotations["select_alias"] == "total"
