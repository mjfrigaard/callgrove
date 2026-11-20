import pytest
from conftest import FIXTURES

from callgrove import CallTree, call_tree_dir

APP = FIXTURES / "demo_app"


def test_tree_from_files():
    tree = call_tree_dir(APP, root="launch", exclude="log_msg")
    assert tree == CallTree(
        "launch",
        [
            CallTree("app_ui", [CallTree("counter_ui", [CallTree("make_label")])]),
            CallTree(
                "app_server",
                [CallTree("counter_server", [CallTree("counter_server.count")])],
            ),
        ],
    )


def test_modules_only_and_max_depth():
    assert call_tree_dir(APP, root="launch", modules_only=True) == CallTree(
        "launch", [CallTree("counter_ui"), CallTree("counter_server")]
    )
    assert call_tree_dir(APP, root="launch", max_depth=1) == CallTree(
        "launch", [CallTree("app_ui"), CallTree("app_server")]
    )


def test_lambda_and_bad_files(tmp_path):
    (tmp_path / "a.py").write_text("f = lambda: g()\ndef g():\n    pass\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    hidden = tmp_path / ".venv"
    hidden.mkdir()
    (hidden / "h.py").write_text("def f():\n    pass\n")
    assert call_tree_dir(tmp_path, root="f") == CallTree("f", [CallTree("g")])


def test_duplicate_definitions_warn(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    (tmp_path / "b.py").write_text("def f():\n    g()\ndef g():\n    pass\n")
    with pytest.warns(UserWarning, match="'f' is defined in both"):
        tree = call_tree_dir(tmp_path, root="f")
    assert tree == CallTree("f", [CallTree("g")])


def test_errors(tmp_path):
    with pytest.raises(NotADirectoryError):
        call_tree_dir(tmp_path / "nope", root="f")
    with pytest.raises(ValueError, match="Could not find"):
        call_tree_dir(tmp_path, root="f")
    with pytest.raises(TypeError):
        call_tree_dir(tmp_path)


def test_launch_string_follows_module_assignment():
    tree = call_tree_dir(APP, root="run", exclude="log_msg", max_depth=3)
    assert tree == CallTree(
        "run",
        [
            CallTree(
                "demo_app.app:app",
                [
                    CallTree("app_ui", [CallTree("counter_ui")]),
                    CallTree("app_server", [CallTree("counter_server")]),
                ],
            )
        ],
    )


def test_launch_string_to_factory_and_unknown_module():
    assert call_tree_dir(APP, root="run_factory", max_depth=2).calls[0].name == (
        "launch"
    )
    assert call_tree_dir(APP, root="run_elsewhere") == CallTree("run_elsewhere")


def test_launch_string_from_parent_folder():
    tree = call_tree_dir(FIXTURES, root="run", max_depth=1)
    assert tree == CallTree("run", [CallTree("demo_app.app:app")])
