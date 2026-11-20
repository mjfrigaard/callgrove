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
    visited: tuple[str, ...] = (),
    depth: int = 1,
) -> CallTree:
    """Depth first build of a CallTree from a ``{name: [callee, ...]}`` graph.

    A name already on the path from the root is skipped, which breaks cycles.
    """
    if max_depth is not None and depth > max_depth:
        return CallTree(node)
    path = (*visited, node)
    children = [c for c in graph.get(node, []) if c not in path]
    return CallTree(
        node, [build_tree(c, graph, max_depth, path, depth + 1) for c in children]
    )


def prune_children(calls: list[CallTree], keep: set[str]) -> list[CallTree]:
    """Keep only nodes named in ``keep``; a dropped node's children move up."""
    out: list[CallTree] = []
    for child in calls:
        grandchildren = prune_children(child.calls, keep)
        if child.name in keep:
            out.append(CallTree(child.name, grandchildren))
        else:
            out.extend(grandchildren)
    return out


def splice_out(calls: list[CallTree], exclude: Iterable[str] | None) -> list[CallTree]:
    """Drop nodes named in ``exclude``; a dropped node's children move up."""
    if not exclude:
        return calls
    exclude = set(exclude)
    out: list[CallTree] = []
    for child in calls:
        grandchildren = splice_out(child.calls, exclude)
        if child.name in exclude:
            out.extend(grandchildren)
        else:
            out.append(CallTree(child.name, grandchildren))
    return out


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
