"""Win probability from exported logistic-regression coefficients. No ML deps at runtime.

The same `features()` is used by model/train.py, so training and serving can't drift.
"""
import json
import math
from pathlib import Path

REG_PERIODS, PERIOD_SECONDS = 4, 720
FEATURES = ["margin", "minutes_left", "margin_over_sqrt_seconds"]


def seconds_left(period: int, clock_seconds: float) -> float:
    """Seconds left in regulation; an OT period is its own short game (just its clock)."""
    if period <= REG_PERIODS:
        return (REG_PERIODS - period) * PERIOD_SECONDS + clock_seconds
    return clock_seconds


def features(margin: float, period: int, clock_seconds: float) -> list[float]:
    s = seconds_left(period, clock_seconds)
    return [margin, s / 60, margin / math.sqrt(s + 1)]


class WinProb:
    def __init__(self, path: Path = Path(__file__).with_name("wp_model.json")):
        m = json.loads(path.read_text())
        assert m["features"] == FEATURES, "model was trained on different features"
        self.b0, self.w = m["intercept"], m["coef"]

    def home(self, home_score: int, away_score: int, period: int, clock_seconds: float) -> float:
        x = features(home_score - away_score, period, clock_seconds)
        z = self.b0 + sum(w * xi for w, xi in zip(self.w, x))
        return 1 / (1 + math.exp(-z))
