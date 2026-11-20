import shiny
from shiny import App, ui

from . import modules
from .modules import counter_server, counter_ui, log_msg


def app_ui():
    return ui.page_fluid(counter_ui("a"), modules.counter_ui("b"))


def app_server(input, output, session):
    log_msg("server")
    counter_server("a")


def launch():
    return App(app_ui(), app_server)


app = App(app_ui(), app_server)
dynamic_app = App(lambda request: app_ui(), app_server)


def one_arg_server(input):
    counter_server("a")


one_arg_app = App(app_ui(), one_arg_server)


def run():
    shiny.run_app("demo_app.app:app")


def run_factory():
    shiny.run_app("demo_app.app:launch", factory=True)


def run_elsewhere():
    shiny.run_app("other_pkg.app:app")
