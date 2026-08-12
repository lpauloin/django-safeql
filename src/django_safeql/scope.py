from contextlib import contextmanager


class ScopeStack:
    def __init__(self):
        self.stack = []

    @contextmanager
    def scoped(self, node, **initial_values):
        self.push(node, **initial_values)
        try:
            yield self.stack[-1]
        finally:
            self.pop(node)

    def push(self, node, **initial_values):
        frame = {"node": node}
        frame.update(initial_values)
        self.stack.append(frame)

    def pop(self, node):
        if not self.stack:
            raise RuntimeError("Scope underflow")
        top = self.stack.pop()
        if top.get("node") is not node:
            raise RuntimeError("Scope mismatch: expected %s, got %s" % (top.get("node"), node))
        return top

    def set(self, key, value):
        if not self.stack:
            raise RuntimeError("No active scope")
        self.stack[-1][key] = value

    def update(self, **values):
        if not self.stack:
            raise RuntimeError("No active scope")
        self.stack[-1].update(values)

    def get(self, key, default=None):
        for frame in reversed(self.stack):
            if key in frame:
                return frame[key]
        return default

    def require(self, key):
        value = self.get(key)
        if value is None:
            raise RuntimeError(f"Missing scope key: {key}")
        return value

    def mutate_mapping(self, key):
        current_frame = self.stack[-1]
        if key not in current_frame:
            # Copy from parent so mutations don't leak up the stack
            parent = self.get(key)
            current_frame[key] = dict(parent) if parent is not None else {}
        mapping = current_frame[key]
        if not isinstance(mapping, dict):
            raise RuntimeError(f"Scope key {key!r} is not a dict")
        return mapping

    def __len__(self):
        return len(self.stack)

    def __repr__(self):
        lines = ["ScopeStack:"]
        for i, frame in enumerate(self.stack):
            node = frame.get("node")
            other_keys = {k: v for k, v in frame.items() if k != "node"}
            if other_keys:
                lines.append(f" [{i}] {node!r} {other_keys!r}")
            else:
                lines.append(f" [{i}] {node!r}")
        return "\n".join(lines)
