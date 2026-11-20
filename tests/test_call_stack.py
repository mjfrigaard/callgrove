import pytest
import sample_mod

from callgrove import CallTree, call_stack


def names(tree):
    return [c.name for c in tree.calls]


def test_follows_calls_in_source_order():
    tree = call_stack("sample_mod.main", max_depth=1)
    assert tree == CallTree(
        "main", [CallTree("log"), CallTree("helper"), CallTree("render")]
    )


def test_cycle_becomes_leaf():
    tree = call_stack("sample_mod.main")
    render = tree.calls[2]
    assert names(render) == ["log", "main", "str"]
    assert render.calls[1].calls == []


def test_accepts_callable():
    assert call_stack(sample_mod.helper, max_depth=1).name == "helper"


def test_singledispatch_methods_are_children():
    tree = call_stack("sample_mod.show", max_depth=1)
    assert names(tree) == ["show[int]", "repr"]


def test_locals_skipped_self_kept():
    assert names(call_stack("sample_mod.uses_locals")) == ["len"]
    assert names(call_stack("sample_mod.Thing.go", max_depth=1)) == [
        "self.step",
        "helper",
    ]


def test_exclude_splices_children_up():
    tree = call_stack("sample_mod.helper", max_depth=2, exclude="log")
    assert names(tree) == ["print", "json.dumps"]


def test_package_only_keeps_other_packages_as_leaves():
    tree = call_stack("sample_mod.helper", package_only=True)
    assert tree == CallTree(
        "helper", [CallTree("log", [CallTree("print")]), CallTree("json.dumps")]
    )


def test_builtin_is_leaf():
    assert call_stack("len") == CallTree("len")


@pytest.mark.parametrize(
    ("fn", "err"),
    [
        ("", ValueError),
        ("no_such_thing", ValueError),
        ("json.nope", ValueError),
        ("json", TypeError),
        (42, TypeError),
    ],
)
def test_bad_fn(fn, err):
    with pytest.raises(err):
        call_stack(fn)


def test_missing_dependency_is_named():
    with pytest.raises(ValueError, match="no_such_dependency_xyz"):
        call_stack("broken_dep.f")


def test_decorated_nested_defs_are_nodes():
    tree = call_stack("sample_mod.outer", max_depth=2)
    assert tree == CallTree(
        "outer",
        [
            CallTree("log", [CallTree("print")]),
            CallTree("outer._", [CallTree("helper")]),
            CallTree("outer._#2"),
        ],
    )


def test_classes_self_and_chained_calls_are_followed():
    assert call_stack("class_mod.summarize") == CallTree(
        "summarize",
        [
            CallTree("Plain"),
            CallTree("Fitter", [CallTree("validate")]),
            CallTree(
                "Fitter().fit",
                [CallTree("self._rows", [CallTree("len")]), CallTree("curve")],
            ),
        ],
    )
