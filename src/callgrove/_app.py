"""call_tree_app(): the call tree of a Shiny for Python App object."""

from __future__ import annotations

import types
import warnings
from collections.abc import Iterable
from typing import Any

from ._source import function_node, is_module_def, lookup, referenced_names, unwrap
from ._tree import CallTree, build_tree, check_args, prune_children, splice_out


def call_tree_app(
    app: Any,
    app_fun: str = "app",
    ui_fun: str | None = None,
    server_fun: str | None = None,
    modules_only: bool = False,
    exclude: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> CallTree:
    """Build the call tree of a Shiny for Python ``App`` object.

    ``call_tree_app()`` takes the server function out of a ``shiny.App`` and
    reads its source. Each name it references is looked up the way the server
    would see it. When the name is a function defined in the app's own
    package (the top level package of the server's module), it joins the tree
    and its source is read the same way. Functions from other packages, such
    as ``shiny.ui``, are left out.

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
    cls = type(app)
    if not (cls.__name__ == "App" and cls.__module__.startswith("shiny")):
        raise TypeError("`app` must be a shiny.App")

    server, _ = unwrap(app.server)
    pkg = getattr(server, "__module__", "").split(".")[0]
    s_name = str(server_fun or getattr(server, "__name__", "server"))

    roots: list[tuple[str, Any]] = [(s_name, server)]
    if ui_fun is not None:
        roots.insert(0, (ui_fun, lookup(ui_fun, server)))
    elif callable(app.ui):
        ui_name = getattr(app.ui, "__name__", "ui")
        roots.insert(0, ("ui" if ui_name == "<lambda>" else ui_name, app.ui))
    else:
        warnings.warn(
            "The app's UI was rendered when App() was created, so its function "
            "can't be found; pass `ui_fun=` to include the UI branch",
            stacklevel=2,
        )

    graph: dict[str, list[str]] = {app_fun: [name for name, _ in roots]}
    modules: set[str] = set()
    queue = list(roots)
    seen = {name for name, _ in roots}
    while queue:
        name, obj = queue.pop(0)
        fun, is_module = unwrap(obj)
        node = function_node(fun) if isinstance(fun, types.FunctionType) else None
        if is_module or (node is not None and is_module_def(node)):
            modules.add(name)
        graph[name] = []
        if node is None:
            continue
        for ref in referenced_names(node):
            target = lookup(ref, fun)
            inner, _ = unwrap(target)
            if ref == name or not _is_local(inner, pkg):
                continue
            graph[name].append(ref)
            if ref not in seen:
                seen.add(ref)
                queue.append((ref, target))

    tree = build_tree(app_fun, graph, max_depth)
    if modules_only:
        tree.calls = prune_children(tree.calls, modules)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


def _is_local(obj: Any, pkg: str) -> bool:
    return isinstance(obj, types.FunctionType) and obj.__module__.split(".")[0] == pkg
