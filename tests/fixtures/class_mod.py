from shiny import App, ui


def validate(n):
    return n


def curve(df):
    return df


class Fitter:
    def __init__(self, n=3):
        self.n = validate(n)

    def fit(self, df):
        self._rows(df)
        return curve(df)

    def _rows(self, df):
        return len(df)


class Plain:
    pass


def summarize(df):
    Plain()
    return Fitter().fit(df)


def class_server(input, output, session):
    summarize(None)


class_app = App(ui.page_fluid(), class_server)
