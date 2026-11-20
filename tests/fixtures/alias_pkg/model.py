def fit_curve(df):
    return df


def is_lower_better(metric):
    return metric == "ERA"


def summarize_career(df):
    return fit_curve(df)


class CareerModel:
    def __init__(self, min_seasons=3):
        self.min_seasons = min_seasons

    def fit(self, df):
        return fit_curve(df)
