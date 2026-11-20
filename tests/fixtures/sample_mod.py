import functools
import json


def log(msg):
    print(msg)


def helper(x):
    log("helper")
    return json.dumps(x)


def main(x):
    log("main")
    y = helper(x)
    return render(y)


def render(y):
    log("render")
    return main(y) if not y else str(y)


@functools.singledispatch
def show(x):
    return repr(x)


@show.register
def _(x: int):
    return helper(x)


def uses_locals(f, items):
    f()
    items.append(1)
    return len(items)


class Thing:
    def go(self):
        self.step()
        return helper(1)

    def step(self):
        pass


def deco(f):
    return f


def outer(x):
    @deco
    def _():
        helper(x)

    @deco
    def _():
        x.method()

    def plain():
        log("plain")

    plain()
    return _
