"""call_tree_app(): the call tree of a Shiny for Python App object."""

from __future__ import annotations

import types
import warnings
from collections.abc import Iterable
from typing import Any

from ._source import (
    FuncNode,
    def_label,
    function_node,
    is_module_def,
    lookup,
    nested_defs,
    nested_helpers,
    referenced_names,
    unwrap,
)
from ._tree import (
    CallTree,
    build_tree,
    check_args,
    check_labels,
    prune_children,
    splice_out,
)

Scope = dict[str, tuple[str, FuncNode]]


def call_tree_app(
    app: Any,
    app_fun: str = "app",
    ui_fun: str | None = None,
    server_fun: str | None = None,
    modules_only: bool = False,
    exclude: str | Iterable[str] | None = None,
    max_depth: int | None = None,
    labels: str = "def",
) -> CallTree:
    """Build the call tree of a Shiny for Python ``App`` object.

    ``call_tree_app()`` takes the server function out of a ``shiny.App`` and
    reads its source. Each name it references is looked up the way the server
    would see it. When the name is a function defined in the app's own
    package (the top level package of the server's module), it joins the tree
    and its source is read the same way. Functions from other packages, such
    as ``shiny.ui``, are left out. A class in the app's package counts
    through its ``__init__``, and ``self.m()`` and ``Class().m()`` are looked
    up on the class, as in `call_stack()`.

    The app is never run, and shiny itself is never imported, so callgrove
    does not depend on it.

    Parameters
    ----------
    app
        A ``shiny.App``.
    app_fun
        Label for the root node. The app does not record the name of the
        function that built it, so this is display text only. Default
        ``"app"``.
    ui_fun
        Name of the UI function. ``App`` renders a static UI when it is
        created, so the function behind it is lost. Pass its name here to
        include the UI branch. When the UI was passed as a function
        (``App(app_ui, server)``), it is found without this. When neither
        applies, the tree has no UI branch and a warning says so.
    server_fun
        Label for the server node. Default: the server function's own name.
    modules_only
        Keep only the root and Shiny module functions; see `call_tree_dir()`.
    exclude
        Function names to drop; see `call_tree_dir()`.
    max_depth
        How many levels to expand. ``None`` (the default) expands everything.
    labels
        ``"def"`` (the default) labels each function by its definition name
        (``Model.fit``), so one function reached under two names is one
        node. ``"call"`` uses the text at the call site (``model.fit``).
        Nested functions are always labeled ``outer.inner``.

    Returns
    -------
    CallTree
        The root node. Print it to draw the tree.

    Warns
    -----
    UserWarning
        When the UI is static and ``ui_fun`` is not given.

    Examples
    --------
    ```python
    from myapp.app import app
    call_tree_app(app, ui_fun="app_ui")
    call_tree_app(app, ui_fun="app_ui", modules_only=True)
    ```
    """
    exclude = check_args(exclude, max_depth)
    labels = check_labels(labels)
    cls = type(app)
    if not (cls.__name__ == "App" and cls.__module__.startswith("shiny")):
        raise TypeError("`app` must be a shiny.App")

    server, _ = unwrap(app.server)
    pkg = getattr(server, "__module__", "").split(".")[0]

    # (key, text drawn in "call" mode, object)
    roots: list[tuple[str, str, Any]] = [
        (_key(server, "server"), getattr(server, "__name__", "server"), server)
    ]
    if ui_fun is not None:
        ui_obj = lookup(ui_fun, server)
        roots.insert(0, (_key(ui_obj, ui_fun), ui_fun, ui_obj))
    elif callable(app.ui):
        roots.insert(0, (_key(app.ui, "ui"), getattr(app.ui, "__name__", "ui"), app.ui))
    else:
        warnings.warn(
            "The app's UI was rendered when App() was created, so its function "
            "can't be found; pass `ui_fun=` to include the UI branch",
            stacklevel=2,
        )

    graph: dict[str, list[str]] = {app_fun: [key for key, _, _ in roots]}
    texts: dict[tuple[str, str], str] = {}
    for key, text, _ in roots:
        texts[(app_fun, key)] = text if text != "<lambda>" else "ui"
    if server_fun is not None:
        texts[(app_fun, roots[-1][0])] = server_fun
    modules: set[str] = set()
    # (key, object, parsed def, helpers in scope); a nested def carries its
    # enclosing function as the object and its own parsed def
    queue: list[tuple[str, Any, FuncNode | None, Scope]] = [
        (key, obj, None, {}) for key, _, obj in roots
    ]
    seen = {key for key, _, _ in roots}
    while queue:
        key, obj, node, inherited = queue.pop(0)
        if node is None:
            fun, is_module = unwrap(obj)
            if isinstance(fun, types.FunctionType):
                node = function_node(fun)
            if is_module or (node is not None and is_module_def(node)):
                modules.add(key)
        else:
            fun = obj
        graph[key] = []
        if node is None:
            continue
        scope = {**inherited, **nested_helpers(node, key)}
        for ref in referenced_names(node):
            if ref in scope:
                child, inner = scope[ref]
                texts[(key, child)] = child
                item: tuple[str, Any, FuncNode | None, Scope] = (
                    child,
                    fun,
                    inner,
                    scope,
                )
            else:
                target = lookup(ref, fun)
                inner_fun, _ = unwrap(target)
                if not _is_local(inner_fun, pkg):
                    continue
                child = def_label(inner_fun)
                texts.setdefault((key, child), ref)
                item = (child, target, None, {})
            if child == key or child in graph[key]:
                continue
            graph[key].append(child)
            if child not in seen:
                seen.add(child)
                queue.append(item)
        for label, inner in nested_defs(node, key):
            graph[key].append(label)
            queue.append((label, fun, inner, scope))

    tree = build_tree(app_fun, graph, max_depth, texts if labels == "call" else None)
    if labels == "def" and server_fun is not None:
        for top in tree.calls:
            if top.key == roots[-1][0]:
                top.name = server_fun
    if modules_only:
        tree.calls = prune_children(tree.calls, modules)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


def _key(obj: Any, fallback: str) -> str:
    """Definition name of a root function, or ``fallback`` when there is none."""
    fun, _ = unwrap(obj)
    if isinstance(fun, types.FunctionType) and fun.__name__ != "<lambda>":
        return def_label(fun)
    return fallback


def _is_local(obj: Any, pkg: str) -> bool:
    return isinstance(obj, types.FunctionType) and obj.__module__.split(".")[0] == pkg
