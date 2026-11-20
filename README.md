# callgrove

`callgrove` draws the call tree of a Python function without running it. Point it at a function and it reads the source to find every function that function calls, the functions those call, and so on. It also follows `functools.singledispatch` functions into each registered implementation.

It is the Python counterpart to the R package [stackcallr](https://mjfrigaard.github.io/stackcallr/).

## Installation

`callgrove` isn't on PyPI. Install the development version from GitHub:

```bash
uv add git+https://github.com/mjfrigaard/callgrove
```

## Usage

`call_stack()` takes a dotted name (or the function itself) and returns the tree of functions it calls. The example below stops two levels down:

```python
>>> from callgrove import call_stack
>>> call_stack("textwrap.dedent", max_depth=2)
█─dedent
├─_whitespace_only_re.sub
├─_leading_whitespace_re.findall
├─enumerate
├─zip
└─█─re.sub
  └─_compile
```

Builtins and C functions have no Python source, so they show as leaves. So do calls that can only be known at run time, such as `self.method()`.

## Shiny module trees

`call_tree_dir()` and `call_tree_app()` build the same kind of tree for a Shiny for Python app, either from a folder of `.py` files on disk or from a `shiny.App` object. Both take `modules_only`, which keeps only functions decorated with `@module.ui` or `@module.server`. Plain wrapper functions are spliced out, so the modules underneath them stay visible:

```python
>>> from callgrove import call_tree_dir
>>> call_tree_dir("src/myapp", root="launch")
█─launch
├─█─app_ui
│ └─counter_ui
└─█─app_server
  └─counter_server
>>> call_tree_dir("src/myapp", root="launch", modules_only=True)
█─launch
├─counter_ui
└─counter_server
```

`call_tree_dir()` never imports the files it scans. Shiny is not a dependency of `callgrove`; you need it only to build the `App` you pass to `call_tree_app()`.

## Functions

`call_stack(fn, max_depth=None, exclude=None)` resolves `fn` and walks its source, following calls and `singledispatch` implementations.

`call_tree_dir(path, root, modules_only=False, exclude=None, max_depth=None)` parses a folder of `.py` files and builds the tree among the top level functions defined there. It warns when two files define the same name.

`call_tree_app(app, app_fun, ui_fun, server_fun, modules_only=False, exclude=None, max_depth=None)` builds the tree of a `shiny.App` from its server function, keeping only functions defined in the app's own package.

All three return a `CallTree`, which prints in the style of R's `lobstr::ast()`. All three take `exclude`, a list of function names to drop (such as a logging helper that appears under every node); each dropped function's children move up into its place.

## Building the documentation

The site is built with [great-docs](https://posit-dev.github.io/great-docs/), which needs Python 3.11 or later and [Quarto](https://quarto.org/). `uv sync` installs the package with the `dev` and `docs` groups:

```bash
uv sync
uv run great-docs build    # writes the site to great-docs/_site/
uv run great-docs preview  # serves it locally
```

The user guide pages live in `user_guide/` and the theme in `docs-theme.css` and `great-docs.yml`. On every push to `main`, `.github/workflows/docs.yaml` builds the site and publishes it to GitHub Pages.
