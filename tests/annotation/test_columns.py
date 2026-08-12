from django_safeql.nodes import BinaryOp, Column


def _left_columns(node):
    """Every left-hand column of a comparison anywhere under ``node``."""
    columns = []
    if isinstance(node, BinaryOp) and isinstance(node.left, Column):
        columns.append(node.left)
    for child in node.children():
        if child is not None:
            columns.extend(_left_columns(child))
    return columns


def test_column_paths(transpiler):
    ast = transpiler.to_ast("""
        SELECT book.*
        FROM book
        JOIN publisher ON book.publisher_id = publisher.id
        JOIN author ON book.author_id = author.id
        WHERE publisher.name = 'Acme'
          AND author.name = 'Invoices'
          AND book.status = 'PARSED_OK'
    """)
    paths = {column.annotations["django_path"] for column in _left_columns(ast.where)}
    assert paths == {"publisher__name", "author__name", "status"}


def test_alias_table(transpiler):
    ast = transpiler.to_ast("""
        SELECT d.*
        FROM book AS d
        JOIN author AS p ON d.author_id = p.id
        WHERE p.name = 'Vernor Vinge'
    """)
    assert ast.where.left.annotations["django_path"] == "author__name"


def test_column_to_column_comparison_paths(transpiler):
    ast = transpiler.to_ast("""
        SELECT book.*
        FROM book
        JOIN author ON book.author_id = author.id
        WHERE book.publisher_id = author.publisher_id
    """)
    assert ast.where.left.annotations["django_path"] == "publisher_id"
    assert ast.where.right.annotations["django_path"] == "author__publisher_id"
