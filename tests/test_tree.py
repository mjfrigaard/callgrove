import pytest

from callgrove import CallTree
from callgrove._tree import build_tree, check_args, prune_children, splice_out


def test_draw_marks_inner_nodes_and_leaves():
    tree = CallTree("a", [CallTree("b", [CallTree("c")]), CallTree("d")])
    assert str(tree) == "█─a\n├─█─b\n│ └─c\n└─d"
    assert repr(tree) == str(tree)


def test_build_tree_breaks_cycles_and_limits_depth():
    graph = {"a": ["b"], "b": ["c", "a"], "c": ["a"]}
    assert build_tree("a", graph) == CallTree("a", [CallTree("b", [CallTree("c")])])
    assert build_tree("a", graph, max_depth=1) == CallTree("a", [CallTree("b")])
    assert build_tree("a", graph, max_depth=0) == CallTree("a")


def test_splice_out_and_prune_move_children_up():
    calls = [CallTree("wrap", [CallTree("mod", [CallTree("log")])])]
    assert splice_out(calls, ["wrap", "log"]) == [CallTree("mod")]
    assert prune_children(calls, {"mod"}) == [CallTree("mod")]
    assert splice_out(calls, []) is calls


def test_check_args():
    assert check_args(None, None) == []
    assert check_args("log", 2) == ["log"]
    assert check_args({"a"}, None) == ["a"]
    with pytest.raises(TypeError):
        check_args([1], None)
    with pytest.raises(TypeError):
        check_args(None, -1)
    with pytest.raises(TypeError):
        check_args(None, True)
