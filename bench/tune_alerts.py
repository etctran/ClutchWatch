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
VARIANTS = {
    "spec": {},
    "reserve(other<=3)": {"OTHER_CAP": 3},
    "reserve(other<=2)": {"OTHER_CAP": 2},
    "late+reserve3": {**LATE, "OTHER_CAP": 3},
    "late+reserve2": {**LATE, "OTHER_CAP": 2},
    "late+reserve2+swing.30": {**LATE, "OTHER_CAP": 2, "SWING_WP": 0.30},
    "late+reserve2+swing.35": {**LATE, "OTHER_CAP": 2, "SWING_WP": 0.35},
    "late+reserve1": {**LATE, "OTHER_CAP": 1},
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
