"""Score alert-rule variants on a season (default 2023-24, the validation season).

  uv run python -m bench.tune_alerts            # needs data/raw/cdnnba_2023.csv
Never run this on 2024-25 to pick a variant: that season is the T8/T9 test set.
"""
import sys
from contextlib import contextmanager

import processor.alerts as A
from ingest.replayer import load_games
from processor.winprob import WinProb

LATE = {"SWING_MIN_PERIOD": 4, "COMEBACK_MIN_PERIOD": 4}
R2 = {**LATE, "OTHER_CAP": 2}
VARIANTS = {
    "spec": {"SWING_MIN_PERIOD": 1, "COMEBACK_MIN_PERIOD": 1, "OTHER_CAP": 4, "SWING_WP": 0.25, "COMEBACK_DEFICIT": 15},
    "v1 late+reserve2 (shipped first)": R2,
    "swing.30": {**R2, "SWING_WP": 0.30},
    "swing.35": {**R2, "SWING_WP": 0.35},
    "swing.40": {**R2, "SWING_WP": 0.40},
    "swing.35+cb18": {**R2, "SWING_WP": 0.35, "COMEBACK_DEFICIT": 18},
    "swing.35+cb20": {**R2, "SWING_WP": 0.35, "COMEBACK_DEFICIT": 20},
    "swing.35+cap1": {**LATE, "OTHER_CAP": 1, "SWING_WP": 0.35},
    "swing.40+cb20": {**R2, "SWING_WP": 0.40, "COMEBACK_DEFICIT": 20},
}


@contextmanager
def knobs(**kw):
    old = {k: getattr(A, k) for k in kw}
    for k, v in kw.items():
        setattr(A, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(A, k, v)


def score(games) -> dict:
    close = close_hit = blow = blow_hit = total = 0
    for rows in games:
        st, fired = A.new_state(), []
        for d in rows:
            a, st = A.evaluate(st, d, d["wp"])
            fired += a
        last = rows[-1]
        m = abs(last["home_score"] - last["away_score"])
        if m <= 3 or max(d["period"] for d in rows) > 4:
            close += 1
            close_hit += any(a.rule == "CLOSE_LATE" for a in fired)
        if m >= 20:
            blow += 1
            blow_hit += bool(fired)
        total += len(fired)
    return {"recall": close_hit / close, "blowout_alerted": blow_hit / blow,
            "alerts_per_game": total / len(games), "n_close": close, "n_blowout": blow}


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2023"
    wp = WinProb()
    games = []
    for g in load_games(f"data/raw/cdnnba_{season}.csv"):
        rows = [e.to_dict() for _, e in g]
        for d in rows:
            d["wp"] = wp.home(d["home_score"], d["away_score"], d["period"], d["clock_seconds"])
        games.append(rows)
    print(f"season {season}: {len(games)} games   targets: recall>=0.90, blowout_alerted<=0.05, alerts/game<=1.5")
    for name, kw in VARIANTS.items():
        with knobs(**kw):
            r = score(games)
        print(f"{name:24s} recall={r['recall']:.3f} ({r['n_close']} close)  "
              f"blowout_alerted={r['blowout_alerted']:.3f} ({r['n_blowout']} blowouts)  alerts/game={r['alerts_per_game']:.2f}")


if __name__ == "__main__":
    main()
