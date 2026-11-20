"""call_stack(): the call tree of an importable function."""

from __future__ import annotations

import builtins
import importlib
import sys
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ._source import (
    FuncNode,
    bound_names,
    called_names,
    def_label,
    function_node,
    init_of,
    lookup,
    nested_defs,
    nested_helpers,
    referenced_names,
    unwrap,
)
from ._tree import CallTree, check_args, check_labels, splice_out


def call_stack(
    fn: str | Callable[..., Any],
    max_depth: int | None = None,
    exclude: str | Iterable[str] | None = None,
    package_only: bool = False,
    labels: str = "def",
) -> CallTree:
    """Build the call tree of a function from its source, without running it.

    ``call_stack()`` reads the function's source, finds every function it
    calls, and follows each of those the same way. Calls to
    ``functools.singledispatch`` functions are followed into every registered
    implementation, which play the part R's ``UseMethod()`` methods do.

    Resolution is static. The function is never called. A class call is
    followed into the class's ``__init__``, ``self.method()`` and
    ``cls.method()`` into the class the caller is defined in, and
    ``Class().method()`` into that method. Calls that can only be known at
    run time (``getattr()``, functions passed in as arguments, methods on a
    parameter) show as leaves or are skipped. Builtins and C extension
    functions have no Python source, so they are leaves too.

    Parameters
    ----------
    fn
        A dotted path such as ``"json.dumps"`` or ``"pkg.module.Class.method"``,
        a bare builtin name such as ``"len"``, or the function itself.
    max_depth
        How many levels to expand. ``None`` (the default) follows every call
        down to a leaf or a function already visited.
    exclude
        Function names to drop from the tree, such as a logging helper that
        appears under every node. A dropped function's children move up into
        its place. The root is never dropped.
    package_only
        When True, only functions from the root's own top level package are
        expanded. Calls into other packages and the standard library stay in
        the tree as leaves. Default False, which follows every call.
    labels
        ``"def"`` (the default) labels a function from the root's own package
        by its definition name (``Model.fit``), and everything else by the
        text at the call site (``re.sub``). ``"call"`` uses the call site
        text everywhere (``model.fit``). Nested functions are always labeled
        ``outer.inner``.

    Returns
    -------
    CallTree
        The root node. Print it to draw the tree.

    Examples
    --------
    >>> call_stack("callgrove.CallTree.__str__")
    █─CallTree.__str__
    ├─_label
    └─█─_draw
      ├─enumerate
      ├─len
      ├─_label
      └─_draw
    >>> call_stack("callgrove.call_tree_dir", max_depth=1, package_only=True)
    █─call_tree_dir
    ...
    """
    exclude = check_args(exclude, max_depth)
    labels = check_labels(labels)
    name, fun = _resolve_fn(fn)
    home = _top_package(init_of(unwrap(fun)[0]))
    ctx = _Ctx(max_depth, set(), home if package_only else None, home, labels)
    tree = _build_node(name, fun, 1, ctx)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


@dataclass
class _Ctx:
    """Settings and state shared by one call_stack() walk."""

    max_depth: int | None
    visited: set[int]
    pkg: str | None  # package_only boundary
    home: str  # the root's top level package, for definition labels
    labels: str

    def within(self, depth: int) -> bool:
        return self.max_depth is None or depth <= self.max_depth


def _resolve_fn(fn: str | Callable[..., Any]) -> tuple[str, Any]:
    """Turn a dotted path (or a callable) into ``(label, function)``."""
    if not isinstance(fn, str):
        if not callable(fn):
            raise TypeError("`fn` must be a dotted name string or a callable")
        return getattr(fn, "__name__", repr(fn)), fn
    if not fn:
        raise ValueError("`fn` must not be empty")

    parts = fn.split(".")
    obj: Any = None
    for i in range(len(parts), 0, -1):
        modname = ".".join(parts[:i])
        try:
            obj = importlib.import_module(modname)
        except ModuleNotFoundError as e:
            # Only a miss on `modname` itself means "try a shorter prefix";
            # a missing dependency inside the module is a real error.
            if e.name is None or modname == e.name or modname.startswith(e.name + "."):
                continue
            raise ValueError(f"Could not resolve `fn = {fn!r}`: {e}") from e
        rest = parts[i:]
        break
    else:
        main = sys.modules.get("__main__")
        if hasattr(builtins, parts[0]):
            obj = builtins
        elif main is not None and hasattr(main, parts[0]):
            obj = main
        else:
            raise ValueError(f"Could not resolve `fn = {fn!r}`: no module or name")
        rest = parts

    for attr in rest:
        try:
            obj = getattr(obj, attr)
        except AttributeError as e:
            raise ValueError(f"Could not resolve `fn = {fn!r}`: {e}") from None
    if not callable(obj):
        raise TypeError(f"`fn = {fn!r}` must resolve to a callable")
    return parts[-1], obj


def _top_package(fun: Any) -> str:
    return str(getattr(fun, "__module__", None) or "").split(".")[0]


def _build_node(
    text: str, obj: Any, depth: int, ctx: _Ctx, fixed: bool = False
) -> CallTree:
    """A node for ``obj`` reached as ``text``; ``fixed`` keeps ``text`` as its label."""
    fun = init_of(unwrap(obj)[0])
    is_func = isinstance(fun, types.FunctionType)
    name = text
    if ctx.labels == "def" and not fixed and is_func and _top_package(fun) == ctx.home:
        name = def_label(fun)
    node = CallTree(name, key=def_label(fun) if is_func else None)
    if (
        not ctx.within(depth)
        or not is_func
        or id(fun) in ctx.visited
        or (ctx.pkg is not None and _top_package(fun) != ctx.pkg)
    ):
        return node
    ctx.visited.add(id(fun))
    fn_node = function_node(fun)
    if fn_node is None:
        return node

    for label, impl in _dispatch_methods(name, obj):
        node.calls.append(_build_node(label, impl, depth + 1, ctx, fixed=True))
    _expand(node, fn_node, fun, set(), {}, frozenset(), depth, ctx)
    return node


def _expand(
    node: CallTree,
    fn_node: FuncNode,
    fun: Any,
    outer: set[str],
    helpers: dict[str, tuple[str, FuncNode]],
    on_path: frozenset[str],
    depth: int,
    ctx: _Ctx,
) -> None:
    """Add a def's calls, then its decorated nested defs, as children of ``node``.

    A nested def has no function object of its own here, so its names are
    looked up through ``fun``, the function it is defined in. ``helpers``
    are the undecorated defs visible from enclosing functions; a helper
    becomes a node where it is called or passed by name. ``on_path`` holds
    the helpers being expanded above this one, so recursion stops.
    """
    prefix = node.key or node.name
    scope = {**helpers, **nested_helpers(fn_node, prefix)}
    local = outer | bound_names(fn_node)
    called = called_names(fn_node, outer, keep=set(scope))
    passed = [r for r in referenced_names(fn_node) if r in scope and r not in called]
    for text in [*called, *passed]:
        if text in scope:
            label, inner = scope[text]
            child = CallTree(label, key=label)
            if label not in on_path and ctx.within(depth + 1):
                _expand(
                    child, inner, fun, local, scope, on_path | {label}, depth + 1, ctx
                )
        else:
            obj = lookup(text, fun)
            child = (
                CallTree(text)
                if obj is None
                else _build_node(text, obj, depth + 1, ctx)
            )
        _add(node, child)
    for label, inner in nested_defs(fn_node, prefix):
        sub = CallTree(label, key=label)
        if ctx.within(depth + 1):
            _expand(sub, inner, fun, local, scope, on_path, depth + 1, ctx)
        _add(node, sub)


def _add(node: CallTree, child: CallTree) -> None:
    """Append ``child`` unless a sibling has its label or stands for the same def."""
    for c in node.calls:
        if c.name == child.name or (child.key is not None and c.key == child.key):
            return
    node.calls.append(child)


def _dispatch_methods(name: str, obj: Any) -> list[tuple[str, Any]]:
    """Registered implementations of a ``functools.singledispatch`` function.

    The ``object`` implementation is the function itself, so it is skipped.
    """
    registry = getattr(obj, "registry", None)
    if registry is None or not hasattr(obj, "dispatch"):
        return []
    return [
        (f"{name}[{getattr(cls, '__name__', cls)}]", impl)
        for cls, impl in registry.items()
        if cls is not object
    ]
