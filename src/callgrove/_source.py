"""Read a function's syntax tree and the names it calls or references."""

from __future__ import annotations

import ast
import builtins
import functools
import inspect
import textwrap
import types
from typing import Any, Union

FuncNode = Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda]

_MODULE_DECORATORS = {
    "module.ui",
    "module.server",
    "shiny.module.ui",
    "shiny.module.server",
}


def dotted_name(node: ast.AST) -> str | None:
    """``a.b.c`` for a Name or a chain of Attributes on a Name, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _body(node: FuncNode) -> list[ast.AST]:
    return [node.body] if isinstance(node, ast.Lambda) else list(node.body)


def _unique(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


def bound_names(node: FuncNode) -> set[str]:
    """Names bound inside a function: parameters, assignments, nested defs, imports.

    Calls through these names are skipped, the way R's
    ``codetools::findGlobals()`` skips local variables.
    """
    bound: set[str] = set()
    declared_global: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                if arg is not None:
                    bound.add(arg.arg)
            if n is not node and not isinstance(n, ast.Lambda):
                bound.add(n.name)
        elif isinstance(n, ast.ClassDef):
            bound.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            declared_global.update(n.names)
    return bound - declared_global


def called_names(node: FuncNode) -> list[str]:
    """Dotted names called in a function's body, in source order, unique.

    Calls through a locally bound name are skipped, except ``self`` and
    ``cls``, which are kept so method calls show as leaves.
    """
    local = bound_names(node) - {"self", "cls"}
    found: list[str] = []

    def visit(n: ast.AST) -> None:
        if isinstance(n, ast.Call):
            name = dotted_name(n.func)
            if name is not None and name.split(".")[0] not in local:
                found.append(name)
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in _body(node):
        visit(stmt)
    return _unique(found)


def referenced_names(node: FuncNode) -> list[str]:
    """Every dotted name loaded in a function's body, called or not, in source order.

    A bare reference counts, so ``App(app_ui, app_server)`` links to both.
    """
    found: list[str] = []

    def visit(n: ast.AST) -> None:
        name = dotted_name(n)
        if name is not None and isinstance(getattr(n, "ctx", None), ast.Load):
            found.append(name)
            return
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in _body(node):
        visit(stmt)
    return _unique(found)


def is_module_def(node: FuncNode) -> bool:
    """True when a def has a Shiny ``@module.ui`` or ``@module.server`` decorator."""
    if isinstance(node, ast.Lambda):
        return False
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if dotted_name(target) in _MODULE_DECORATORS:
            return True
    return False


def function_node(fun: Any) -> FuncNode | None:
    """Parse a function's source into its def or lambda node.

    Returns None when there is no source to read (builtins, C extensions,
    functions typed into a REPL) or it does not parse on its own.
    """
    try:
        src = textwrap.dedent(inspect.getsource(fun))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError):
        return None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return n
    return None


def _closure_var(fun: Any, name: str) -> Any:
    code = getattr(fun, "__code__", None)
    if code is None or fun.__closure__ is None or name not in code.co_freevars:
        return None
    try:
        return fun.__closure__[code.co_freevars.index(name)].cell_contents
    except ValueError:
        return None


def unwrap(obj: Any) -> tuple[Any, bool]:
    """Peel decorators off a callable.

    Follows ``__wrapped__`` (``functools.wraps``), bound methods, partials, and
    the closures Shiny uses for ``@module.ui``, ``@module.server``, and one
    argument server functions. Returns the inner callable and whether a Shiny
    module decorator was removed.
    """
    is_module = False
    for _ in range(50):
        if isinstance(obj, types.MethodType):
            obj = obj.__func__
        elif isinstance(obj, functools.partial):
            obj = obj.func
        elif getattr(obj, "__module__", None) == "shiny.module" and _closure_var(
            obj, "fn"
        ):
            obj = _closure_var(obj, "fn")
            is_module = True
        elif getattr(obj, "__module__", None) == "shiny._app" and _closure_var(
            obj, "server"
        ):
            obj = _closure_var(obj, "server")
        elif hasattr(obj, "__wrapped__"):
            obj = obj.__wrapped__
        else:
            break
    return obj, is_module


def lookup(name: str, fun: Any) -> Any:
    """Resolve a dotted name the way ``fun`` would see it at call time.

    Looks in the closure, then the module globals, then builtins, then follows
    attributes. Returns None when any step fails.
    """
    base, *rest = name.split(".")
    missing = object()
    obj = _closure_var(fun, base)
    if obj is None:
        obj = getattr(fun, "__globals__", {}).get(base, missing)
    if obj is missing:
        obj = getattr(builtins, base, missing)
    if obj is missing:
        return None
    for attr in rest:
        try:
            obj = getattr(obj, attr)
        except Exception:
            return None
    return obj
