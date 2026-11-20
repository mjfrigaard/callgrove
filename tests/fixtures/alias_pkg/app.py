import alias_pkg.model
import alias_pkg.model as mdl
from alias_pkg.model import CareerModel

from . import plots
from .model import summarize_career as summarize

_model = CareerModel()


def server():
    plots.plot_empty("x")
    _model.fit(None)
    plots.plot_trajectory(None)
    mdl.is_lower_better("ERA")
    summarize(None)
    alias_pkg.model.fit_curve(None)
