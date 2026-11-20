"""call_tree_dir(): the call tree of the functions defined in a folder of .py files."""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterable
from pathlib import Path

from ._source import FuncNode, is_module_def, launch_targets, referenced_names
from ._tree import CallTree, build_tree, check_args, prune_children, splice_out

_SKIP_DIRS = {"__pycache__", "site-packages", "node_modules"}


def call_tree_dir(
    path: str | Path = "src",
    root: str = "",
    modules_only: bool = False,
    exclude: str | Iterable[str] | None = None,
    max_depth: int | None = None,
) -> CallTree:
    """Build the call tree of the functions defined in a folder of ``.py`` files.

    ``call_tree_dir()`` parses every ``.py`` file under ``path`` (subfolders
    included) without importing or running any of it. It collects each top
    level function (``def name(...)`` or ``name = lambda ...``) and links a
    function to every other collected function its body calls or names. The
    result is the tree reachable from ``root``.

    Because nothing is imported, it works on a package's ``src/`` folder or a
    Shiny for Python app before it is installed.

    A launch function often names the app as a string, as in
    ``shiny.run_app("myapp.app:app")``. Such a ``"module:attr"`` string is
    followed when ``module`` is one of the scanned files. When ``attr`` is a
    module level assignment (``app = create_app()``), the string becomes a
    node whose children are the functions that assignment calls or names.
    When ``attr`` is a function (an app factory), it links straight to it.

    Parameters
    ----------
    path
        Folder to scan. Default ``"src"``.
    root
        Name of the function to root the tree at. It must be one of the top
        level functions found under ``path``.
    modules_only
        When True, keep only ``root`` and functions decorated with Shiny's
        ``@module.ui`` or ``@module.server``. Every other function is spliced
        out and its children move up, so modules reached through a plain
        wrapper stay visible.
    exclude
        Function names to drop from the tree; their children move up into
        their place. The root is never dropped.
    max_depth
        How many levels to expand. ``None`` (the default) expands everything.

    Returns
    -------
    CallTree
        The root node. Print it to draw the tree.

    Warns
    -----
    UserWarning
        When two files define a top level function with the same name. The
        file parsed last (in sorted path order) wins.

    Examples
    --------
    >>> import tempfile
    >>> from pathlib import Path
    >>> app_dir = Path(tempfile.mkdtemp())
    >>> _ = (app_dir / "app.py").write_text('''
    ... from shiny import App, module, ui
    ...
    ... @module.ui
    ... def counter_ui():
    ...     return ui.input_action_button("go", "Go")
    ...
    ... @module.server
    ... def counter_server(input, output, session):
    ...     pass
    ...
    ... def app_ui():
    ...     return ui.page_fluid(counter_ui("a"))
    ...
    ... def app_server(input, output, session):
    ...     counter_server("a")
    ...
    ... def launch():
    ...     return App(app_ui(), app_server)
    ... ''')
    >>> call_tree_dir(app_dir, root="launch")
    █─launch
    ├─█─app_ui
    │ └─counter_ui
    └─█─app_server
      └─counter_server
    >>> call_tree_dir(app_dir, root="launch", modules_only=True)
    █─launch
    ├─counter_ui
    └─counter_server
    """
    exclude = check_args(exclude, max_depth)
    if not isinstance(root, str) or not root:
        raise TypeError("`root` must be a non-empty string")
    path = Path(path)
    if not path.is_dir():
        raise NotADirectoryError(f"`path` is not a folder: {str(path)!r}")

    scan = _parse_dir(path)
    defs = scan.defs
    if root not in defs:
        raise ValueError(
            f"Could not find a top level function named {root!r} in {str(path)!r}"
        )

    known = set(defs)
    graph: dict[str, list[str]] = {}
    for name, node in defs.items():
        children = [r for r in referenced_names(node) if r in known and r != name]
        for text, module, attr in launch_targets(node):
            child = _follow_target(scan, text, module, attr, known, graph)
            if child is not None and child != name and child not in children:
                children.append(child)
        graph[name] = children
    tree = build_tree(root, graph, max_depth)
    if modules_only:
        modules = {name for name, node in defs.items() if is_module_def(node)}
        tree.calls = prune_children(tree.calls, modules)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


class _Scan:
    """What one pass over a folder found."""

    def __init__(self) -> None:
        # top level functions, by name
        self.defs: dict[str, FuncNode] = {}
        # dotted module path of the file each function came from
        self.def_module: dict[str, tuple[str, ...]] = {}
        # module level `name = value` assignments, per dotted module path
        self.assigns: dict[tuple[str, ...], dict[str, ast.expr]] = {}


def _module_parts(path: Path, rel: tuple[str, ...]) -> tuple[str, ...]:
    """Dotted module path of a file; a package folder adds its own name first."""
    parts = [*rel[:-1], rel[-1].removesuffix(".py")]
    if parts[-1] == "__init__":
        parts.pop()
    if (path / "__init__.py").is_file():
        parts.insert(0, path.resolve().name)
    return tuple(parts)


def _find_module(scan: _Scan, module: str) -> tuple[str, ...] | None:
    """The scanned module a dotted name points at: exact match, else longest tail."""
    target = tuple(module.split("."))
    if target in scan.assigns:
        return target
    tails = [m for m in scan.assigns if m and target[-len(m) :] == m]
    return max(tails, key=len) if tails else None


def _follow_target(
    scan: _Scan,
    text: str,
    module: str,
    attr: str,
    known: set[str],
    graph: dict[str, list[str]],
) -> str | None:
    """Graph name for a ``"module:attr"`` string, adding a node for it if needed."""
    mod = _find_module(scan, module)
    if mod is None:
        return None
    value = scan.assigns[mod].get(attr)
    if value is not None:
        graph.setdefault(text, [r for r in referenced_names(value) if r in known])
        return text
    if attr in known and scan.def_module[attr] == mod:
        return attr
    return None


def _parse_dir(path: Path) -> _Scan:
    """Top level functions and assignments under ``path``.

    Files that cannot be read or parsed are skipped.
    """
    scan = _Scan()
    defs = scan.defs
    where: dict[str, Path] = {}
    for file in sorted(path.rglob("*.py")):
        rel = file.relative_to(path).parts
        if any(p.startswith(".") or p in _SKIP_DIRS for p in rel[:-1]):
            continue
        try:
            module = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        mod = _module_parts(path, rel)
        scan.assigns[mod] = _top_level_assigns(module)
        for name, node in _top_level_defs(module):
            if name in defs and where[name] != file:
                warnings.warn(
                    f"{name!r} is defined in both {where[name]} and {file}; "
                    f"using {file}",
                    stacklevel=3,
                )
            defs[name] = node
            where[name] = file
            scan.def_module[name] = mod
    return scan


def _top_level_assigns(module: ast.Module) -> dict[str, ast.expr]:
    out: dict[str, ast.expr] = {}
    for stmt in module.body:
        if isinstance(stmt, ast.Assign) and not isinstance(stmt.value, ast.Lambda):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            if isinstance(stmt.target, ast.Name):
                out[stmt.target.id] = stmt.value
    return out


def _top_level_defs(module: ast.Module) -> list[tuple[str, FuncNode]]:
    out: list[tuple[str, FuncNode]] = []
    for stmt in module.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((stmt.name, stmt))
        elif (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Lambda)
        ):
            out.append((stmt.targets[0].id, stmt.value))
    return out
