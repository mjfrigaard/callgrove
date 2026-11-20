from shiny import App, render, ui


def weight_of(x):
    return x


def helper_server(input, output, session):
    def _weight():
        return weight_of(input.position())

    def _unused():
        return weight_of(None)

    @render.text
    def plot():
        return _weight()

    @render.text
    def table():
        return _weight()


helper_app = App(ui.page_fluid(), helper_server)
