class Visitor:
    def visit(self, node, *args, **kwargs):
        if node is None:
            return None
        method = getattr(self, f"visit_{node.__class__.__name__}", self.generic_visit)
        return method(node, *args, **kwargs)

    def generic_visit(self, node, *args, **kwargs):
        for child in node.children():
            self.visit(child, *args, **kwargs)
        return node
