"""call_stack(): the call tree of an importable function."""

from __future__ import annotations

import builtins
import importlib
import sys
import types
from collections.abc import Callable, Iterable
from typing import Any

from ._source import called_names, function_node, lookup, unwrap
from ._tree import CallTree, check_args, splice_out


def call_stack(
    fn: str | Callable[..., Any],
    max_depth: int | None = None,
    exclude: str | Iterable[str] | None = None,
    package_only: bool = False,
) -> CallTree:
    """Build the call tree of a function from its source, without running it.

    ``call_stack()`` reads the function's source, finds every function it
    calls, and follows each of those the same way. Calls to
    ``functools.singledispatch`` functions are followed into every registered
    implementation, which play the part R's ``UseMethod()`` methods do.

    Resolution is static. The function is never called. Calls that can only
    be known at run time (``self.method()``, ``getattr()``, functions passed
    in as arguments) show as leaves or are skipped. Builtins and C extension
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

    Returns
    -------
    CallTree
        The root node. Print it to draw the tree.

    Examples
    --------
    >>> call_stack("callgrove.CallTree.__str__")
    █─__str__
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
    name, fun = _resolve_fn(fn)
    pkg = _top_package(unwrap(fun)[0]) if package_only else None
    tree = _build_node(name, fun, 1, max_depth, set(), pkg)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


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
    name: str,
    obj: Any,
    depth: int,
    max_depth: int | None,
    visited: set[int],
    pkg: str | None = None,
) -> CallTree:
    node = CallTree(name)
    fun, _ = unwrap(obj)
    if (
        (max_depth is not None and depth > max_depth)
        or not isinstance(fun, types.FunctionType)
        or id(fun) in visited
        or (pkg is not None and _top_package(fun) != pkg)
    ):
        return node
    visited.add(id(fun))
    fn_node = function_node(fun)
    if fn_node is None:
        return node

    for label, impl in _dispatch_methods(name, obj):
        node.calls.append(_build_node(label, impl, depth + 1, max_depth, visited, pkg))
    for label in called_names(fn_node):
        child = lookup(label, fun)
        if child is None:
            node.calls.append(CallTree(label))
        else:
            node.calls.append(
                _build_node(label, child, depth + 1, max_depth, visited, pkg)
            )
    return node


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
