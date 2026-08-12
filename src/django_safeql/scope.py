from contextlib import contextmanager

NODE_TYPES = "node_types"


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

    def get(self, key, default=None):
        for frame in reversed(self.stack):
            if key in frame:
                return frame[key]
        return default

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

    # -- Subtree type recording -------------------------------------------
    #
    # A scope can ask "what node types live under me?" without walking its own
    # subtree: it calls record_types(), and every node announced during the walk
    # below lands in that set. Read as a whitelist, a node type nobody planned for
    # shows up in the set instead of slipping through unnoticed.

    def record_types(self):
        """Start recording, on the current scope, the node types living below it."""
        self.set(NODE_TYPES, set())

    def announce(self, node_type):
        """Record a node type into the nearest recording scope, if any."""
        for frame in reversed(self.stack):
            if NODE_TYPES in frame:
                frame[NODE_TYPES].add(node_type)
                return

    def types(self):
        return self.get(NODE_TYPES, set())

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
