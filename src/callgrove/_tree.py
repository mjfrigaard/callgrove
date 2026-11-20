"""The CallTree node, how it is drawn, and the helpers that reshape it."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass(repr=False)
class CallTree:
    """One node of a call tree: a function name and the calls it makes.

    Every tree builder in callgrove returns a ``CallTree``. Printing it (or
    showing it in a REPL) draws the tree in the style of R's
    ``lobstr::ast()``. A node with children is prefixed with ``█─``; a leaf is
    plain text. Children hang off ``├─`` and ``└─`` branches, one indent per
    level.

    Parameters
    ----------
    name
        The function name, as written at the call site.
    calls
        Child nodes, in the order the calls appear in the source.

    Examples
    --------
    >>> CallTree("main", [CallTree("load", [CallTree("open")]), CallTree("run")])
    █─main
    ├─█─load
    │ └─open
    └─run
    """

    name: str
    calls: list[CallTree] = field(default_factory=list)
    # the definition this node stands for, when `name` is call site text;
    # used by `exclude` and `modules_only`, never drawn or compared
    key: str | None = field(default=None, compare=False)

    def __str__(self) -> str:
        lines = [_label(self)]
        _draw(self.calls, "", lines)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)


def _label(node: CallTree) -> str:
    return f"█─{node.name}" if node.calls else node.name


def _draw(calls: list[CallTree], prefix: str, lines: list[str]) -> None:
    for i, child in enumerate(calls):
        last = i == len(calls) - 1
        lines.append(f"{prefix}{'└─' if last else '├─'}{_label(child)}")
        _draw(child.calls, prefix + ("  " if last else "│ "), lines)


def build_tree(
    node: str,
    graph: Mapping[str, list[str]],
    max_depth: int | None = None,
    labels: Mapping[tuple[str, str], str] | None = None,
    visited: tuple[str, ...] = (),
    depth: int = 1,
    label: str | None = None,
) -> CallTree:
    """Depth first build of a CallTree from a ``{key: [callee key, ...]}`` graph.

    ``labels`` maps a ``(caller, callee)`` edge to the text drawn for the
    callee; without an entry the key itself is drawn. A key already on the
    path from the root is skipped, which breaks cycles.
    """
    out = CallTree(label or node, key=node)
    if max_depth is not None and depth > max_depth:
        return out
    path = (*visited, node)
    for c in graph.get(node, []):
        if c not in path:
            text = (labels or {}).get((node, c))
            out.calls.append(
                build_tree(c, graph, max_depth, labels, path, depth + 1, text)
            )
    return out


def _ids(node: CallTree) -> set[str]:
    return {node.name} if node.key is None else {node.name, node.key}


def prune_children(calls: list[CallTree], keep: set[str]) -> list[CallTree]:
    """Keep nodes named (or keyed) in ``keep``; a dropped node's children move up."""
    out: list[CallTree] = []
    for child in calls:
        grandchildren = prune_children(child.calls, keep)
        if _ids(child) & keep:
            out.append(CallTree(child.name, grandchildren, child.key))
        else:
            out.extend(grandchildren)
    return out


def splice_out(calls: list[CallTree], exclude: Iterable[str] | None) -> list[CallTree]:
    """Drop nodes named (or keyed) in ``exclude``; their children move up."""
    if not exclude:
        return calls
    exclude = set(exclude)
    out: list[CallTree] = []
    for child in calls:
        grandchildren = splice_out(child.calls, exclude)
        if _ids(child) & exclude:
            out.extend(grandchildren)
        else:
            out.append(CallTree(child.name, grandchildren, child.key))
    return out


def check_labels(labels: object) -> str:
    if labels not in ("def", "call"):
        raise ValueError('`labels` must be "def" or "call"')
    return str(labels)


def check_args(exclude: object, max_depth: object) -> list[str]:
    """Validate the ``exclude`` and ``max_depth`` arguments shared by every builder.

    Returns ``exclude`` as a list (a single string becomes a one item list).
    """
    if max_depth is not None and (
        not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0
    ):
        raise TypeError("`max_depth` must be None or a non-negative integer")
    if exclude is None:
        return []
    if isinstance(exclude, str):
        return [exclude]
    if isinstance(exclude, Iterable):
        items = list(exclude)
        if all(isinstance(x, str) for x in items):
            return items
    raise TypeError("`exclude` must be None, a string, or an iterable of strings")
