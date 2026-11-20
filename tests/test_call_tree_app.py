import pytest
from demo_app.app import app, dynamic_app, one_arg_app

from callgrove import CallTree, call_tree_app


def test_static_ui_without_ui_fun_warns():
    with pytest.warns(UserWarning, match="pass `ui_fun=`"):
        tree = call_tree_app(app, exclude="log_msg")
    assert tree == CallTree(
        "app",
        [
            CallTree(
                "app_server",
                [CallTree("counter_server", [CallTree("counter_server.count")])],
            )
        ],
    )


def test_ui_fun_adds_ui_branch():
    tree = call_tree_app(app, ui_fun="app_ui", exclude="log_msg")
    ui = tree.calls[0]
    assert ui.name == "app_ui"
    assert [c.name for c in ui.calls] == ["counter_ui", "modules.counter_ui"]


def test_dynamic_ui_found_without_ui_fun():
    tree = call_tree_app(dynamic_app, app_fun="launch", max_depth=2)
    assert tree == CallTree(
        "launch",
        [
            CallTree("ui", [CallTree("app_ui")]),
            CallTree("app_server", [CallTree("log_msg"), CallTree("counter_server")]),
        ],
    )


def test_modules_only_unwraps_shiny_decorators():
    tree = call_tree_app(one_arg_app, ui_fun="app_ui", modules_only=True)
    assert [c.name for c in tree.calls] == [
        "counter_ui",
        "modules.counter_ui",
        "counter_server",
    ]


def test_rejects_non_app():
    with pytest.raises(TypeError, match="shiny.App"):
        call_tree_app(object())
