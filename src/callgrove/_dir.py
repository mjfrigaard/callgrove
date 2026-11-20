"""call_tree_dir(): the call tree of the functions defined in a folder of .py files."""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterable
from pathlib import Path

from ._source import (
    FuncNode,
    dotted_name,
    is_module_def,
    launch_targets,
    nested_defs,
    referenced_names,
)
from ._tree import CallTree, build_tree, check_args, prune_children, splice_out

# generated or vendored folders; great-docs and _freeze are docs build output
_SKIP_DIRS = {"__pycache__", "site-packages", "node_modules", "great-docs", "_freeze"}


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
    level function (``def name(...)`` or ``name = lambda ...``) and each
    class method (as ``Class.method``), then links a function to every other
    collected function its body calls or names. The result is the tree
    reachable from ``root``.

    Names are resolved through each file's imports, so ``mdl.fit()`` after
    ``import pkg.model as mdl``, ``plots.draw()`` after ``from . import
    plots``, and ``g()`` after ``from .m import f as g`` all link to the
    function they name. A module level instance (``model = Model()``) links
    ``model.fit()`` to ``Model.fit``. A class call links to
    ``Class.__init__`` when the class defines one, ``Class().fit()`` links
    to ``Class.fit``, and ``self.m()`` or ``cls.m()`` inside a method links
    to ``m`` on the same class (base classes are not searched). Nodes are
    labeled with the name of the definition, not the alias used at the call
    site. Folders named ``great-docs`` or ``_freeze`` (docs build output)
    and hidden folders are skipped.

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
        Name of the function to root the tree at: a top level function found
        under ``path``, or a method written as ``"Class.method"``.
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

    graph: dict[str, list[str]] = {}
    for name, node in defs.items():
        mod = scan.def_module[name]
        cls = scan.def_class[name]
        children = _resolve_refs(scan, mod, node, cls, exclude_self=name)
        for text, module, attr in launch_targets(node):
            child = _follow_target(scan, text, module, attr, graph)
            if child is not None and child != name and child not in children:
                children.append(child)
        graph[name] = children
        _add_nested(scan, mod, cls, name, node, graph)
    tree = build_tree(root, graph, max_depth)
    if modules_only:
        modules = {name for name, node in defs.items() if is_module_def(node)}
        tree.calls = prune_children(tree.calls, modules)
    tree.calls = splice_out(tree.calls, exclude)
    return tree


def _resolve_refs(
    scan: _Scan,
    mod: Mod,
    node: ast.AST,
    cls: str | None = None,
    exclude_self: str | None = None,
) -> list[str]:
    """Graph names of the scanned functions a def (or expression) refers to.

    ``cls`` is the class the def is a method of, for ``self`` and ``cls``.
    """
    out: list[str] = []
    for ref in referenced_names(node):
        key = _resolve(scan, mod, ref, cls)
        if key is not None and key != exclude_self and key not in out:
            out.append(key)
    return out


def _add_nested(
    scan: _Scan,
    mod: Mod,
    cls: str | None,
    name: str,
    node: FuncNode,
    graph: dict[str, list[str]],
) -> None:
    """Give each decorated def nested in ``node`` its own graph entry."""
    for label, inner in nested_defs(node, name):
        graph[name].append(label)
        graph[label] = _resolve_refs(scan, mod, inner, cls)
        _add_nested(scan, mod, cls, label, inner, graph)


Mod = tuple[str, ...]
# What a name points at while resolving: ("func", key), ("class", name),
# ("instance", class name), or ("module", dotted name)
Target = tuple[str, str]


class _Scan:
    """What one pass over a folder found."""

    def __init__(self) -> None:
        # functions by graph name: `f` for top level, `Class.method` for methods
        self.defs: dict[str, FuncNode] = {}
        # module each graph name was defined in, and its class for a method
        self.def_module: dict[str, Mod] = {}
        self.def_class: dict[str, str | None] = {}
        # per module: top level assignments, function names, class names,
        # and imports (bound name -> absolute dotted name, or (module, attr))
        self.assigns: dict[Mod, dict[str, ast.expr]] = {}
        self.funcs: dict[Mod, set[str]] = {}
        self.classes: dict[Mod, set[str]] = {}
        self.imports: dict[Mod, dict[str, str | tuple[str, str]]] = {}
        # method names per class
        self.methods: dict[str, set[str]] = {}


def _module_parts(path: Path, rel: tuple[str, ...]) -> Mod:
    """Dotted module path of a file; a package folder adds its own name first."""
    parts = [*rel[:-1], rel[-1].removesuffix(".py")]
    if parts[-1] == "__init__":
        parts.pop()
    if (path / "__init__.py").is_file():
        parts.insert(0, path.resolve().name)
    return tuple(parts)


def _find_module(scan: _Scan, module: str) -> Mod | None:
    """The scanned module a dotted name points at.

    An exact match wins. Otherwise a scanned path that ends the name
    (``app`` for ``myapp.app``, when scanning inside the package) or, for a
    name with two or more parts, a scanned path the name ends
    (``src.myapp.app`` for ``myapp.app``, when scanning above ``src/``).
    The closest match in length wins.
    """
    target = tuple(module.split("."))
    if target in scan.assigns:
        return target
    hits = [m for m in scan.assigns if m and target[-len(m) :] == m]
    if len(target) >= 2:
        hits += [m for m in scan.assigns if m[-len(target) :] == target]
    return min(hits, key=lambda m: abs(len(m) - len(target))) if hits else None


def _resolve(scan: _Scan, mod: Mod, dotted: str, cls: str | None = None) -> str | None:
    """Graph name a dotted reference in module ``mod`` points at, if it is scanned.

    Follows the file's imports (``import a.b as m``, ``from . import m``,
    ``from .m import f as g``), classes, and module level instances
    (``x = Class()``, then ``x.method``). Inside a method of ``cls``,
    ``self.m`` and ``cls.m`` point at ``cls.m``. ``Class().m`` points at
    ``Class.m``, and a class itself at ``Class.__init__`` when it defines one.
    """
    head, sep, tail = dotted.partition("().")
    target = _target(scan, mod, head, cls)
    if sep:
        if target is None or target[0] != "class":
            return None
        target = ("instance", target[1])
        for attr in tail.split("."):
            target = _attr(scan, target, attr) if target is not None else None
    if target is None:
        # a bare name with no binding in this file: fall back to any top level
        # function of that name, as before imports were read
        return dotted if "." not in dotted and dotted in scan.defs else None
    kind, key = target
    if kind == "class" and "__init__" in scan.methods.get(key, ()):
        return f"{key}.__init__"
    return key if kind == "func" else None


def _target(scan: _Scan, mod: Mod, dotted: str, cls: str | None) -> Target | None:
    """What a dotted name (no call in it) points at in module ``mod``."""
    base, *rest = dotted.split(".")
    if base in ("self", "cls"):
        target: Target | None = ("instance", cls) if cls is not None else None
    else:
        target = _lookup(scan, mod, base, set())
    for attr in rest:
        if target is None:
            return None
        target = _attr(scan, target, attr)
    return target


def _lookup(
    scan: _Scan, mod: Mod, name: str, seen: set[tuple[Mod, str]]
) -> Target | None:
    """What ``name`` is bound to at the top level of module ``mod``."""
    if (mod, name) in seen:
        return None
    seen.add((mod, name))
    if name in scan.funcs.get(mod, ()):
        return ("func", name)
    if name in scan.classes.get(mod, ()):
        return ("class", name)
    imp = scan.imports.get(mod, {}).get(name)
    if isinstance(imp, str):
        return ("module", imp)
    if isinstance(imp, tuple):
        source, attr = imp
        if _find_module(scan, f"{source}.{attr}") is not None:
            return ("module", f"{source}.{attr}")
        src = _find_module(scan, source)
        return _lookup(scan, src, attr, seen) if src is not None else None
    value = scan.assigns.get(mod, {}).get(name)
    if isinstance(value, ast.Call):
        func = dotted_name(value.func)
        if func is not None:
            made = _lookup(scan, mod, func.split(".")[0], seen)
            for attr in func.split(".")[1:]:
                made = _attr(scan, made, attr) if made is not None else None
            if made is not None and made[0] == "class":
                return ("instance", made[1])
    if mod + (name,) in scan.assigns:
        return ("module", ".".join(mod + (name,)))
    return None


def _attr(scan: _Scan, target: Target, attr: str) -> Target | None:
    """What ``target.attr`` points at."""
    kind, key = target
    if kind == "module":
        found = _find_module(scan, key)
        if found is not None:
            hit = _lookup(scan, found, attr, set())
            if hit is not None:
                return hit
        return ("module", f"{key}.{attr}")
    if kind in ("class", "instance") and attr in scan.methods.get(key, ()):
        return ("func", f"{key}.{attr}")
    return None


def _follow_target(
    scan: _Scan,
    text: str,
    module: str,
    attr: str,
    graph: dict[str, list[str]],
) -> str | None:
    """Graph name for a ``"module:attr"`` string, adding a node for it if needed."""
    mod = _find_module(scan, module)
    if mod is None:
        return None
    value = scan.assigns[mod].get(attr)
    if value is not None:
        graph.setdefault(text, _resolve_refs(scan, mod, value))
        return text
    if attr in scan.funcs.get(mod, ()):
        return attr
    return None


def _parse_dir(path: Path) -> _Scan:
    """Functions, classes, imports, and assignments under ``path``.

    Files that cannot be read or parsed are skipped.
    """
    scan = _Scan()
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
        package = mod if file.name == "__init__.py" else mod[:-1]
        scan.assigns[mod] = _top_level_assigns(module)
        scan.imports[mod] = _top_level_imports(module, package)
        scan.funcs[mod] = set()
        scan.classes[mod] = set()
        for name, node, cls in _top_level_defs(module):
            if cls is None:
                scan.funcs[mod].add(name)
            else:
                scan.classes[mod].add(cls)
                scan.methods.setdefault(cls, set()).add(name.split(".", 1)[1])
            if name in scan.defs and where[name] != file:
                warnings.warn(
                    f"{name!r} is defined in both {where[name]} and {file}; "
                    f"using {file}",
                    stacklevel=3,
                )
            scan.defs[name] = node
            where[name] = file
            scan.def_module[name] = mod
            scan.def_class[name] = cls
        for stmt in module.body:
            if isinstance(stmt, ast.ClassDef):
                scan.classes[mod].add(stmt.name)
                scan.methods.setdefault(stmt.name, set())
    return scan


def _top_level_imports(
    module: ast.Module, package: Mod
) -> dict[str, str | tuple[str, str]]:
    """Names bound by top level imports, mapped to absolute dotted names.

    ``import a.b as m`` gives ``{"m": "a.b"}``; ``import a.b`` gives
    ``{"a": "a"}``; ``from .m import f as g`` gives ``{"g": ("pkg.m", "f")}``.
    """
    out: dict[str, str | tuple[str, str]] = {}
    for stmt in module.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    out[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    out[top] = top
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.level:
                keep = len(package) - (stmt.level - 1)
                if keep < 0:
                    continue
                parts = [*package[:keep], *(stmt.module or "").split(".")]
                source = ".".join(p for p in parts if p)
            else:
                source = stmt.module or ""
            for alias in stmt.names:
                if alias.name != "*":
                    out[alias.asname or alias.name] = (source, alias.name)
    return out


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


def _top_level_defs(module: ast.Module) -> list[tuple[str, FuncNode, str | None]]:
    """Top level functions and lambdas, plus class methods as ``Class.method``.

    Each item is (graph name, def, class name or None).
    """
    out: list[tuple[str, FuncNode, str | None]] = []
    for stmt in module.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((stmt.name, stmt, None))
        elif (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Lambda)
        ):
            out.append((stmt.targets[0].id, stmt.value, None))
        elif isinstance(stmt, ast.ClassDef):
            for item in stmt.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append((f"{stmt.name}.{item.name}", item, stmt.name))
    return out
