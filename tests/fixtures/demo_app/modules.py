from shiny import module, render, ui


def log_msg(msg):
    return msg


def make_label(text):
    log_msg("label")
    return text.title()


@module.ui
def counter_ui(label="Count"):
    log_msg("counter_ui")
    return ui.input_action_button("go", make_label(label))


@module.server
def counter_server(input, output, session):
    log_msg("counter_server")

    @render.text
    def count():
        return str(input.go())
