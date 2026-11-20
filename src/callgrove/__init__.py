"""Statically inspect and draw the call tree of a Python function.

Python counterpart to the R package stackcallr.
"""

from ._app import call_tree_app
from ._dir import call_tree_dir
from ._stack import call_stack
from ._tree import CallTree

__all__ = ["CallTree", "call_stack", "call_tree_app", "call_tree_dir"]
