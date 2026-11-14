"""Train the win-probability model and export coefficients to processor/wp_model.json.

One row per scoring event. Train 2020-21..2022-23, validate 2023-24, test 2024-25
(cdnnba archive starts at 2020-21; see docs/DECISIONS.md).

  uv run --group model python -m model.train
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from ingest.normalize import parse_clock
from processor.winprob import FEATURES, features

RAW = Path("data/raw")
CACHE = Path("data/rows")
SPLITS = {"train": [2020, 2021, 2022], "val": [2023], "test": [2024], "test_2025": [2025]}
OUT = Path("processor/wp_model.json")


def season_rows(season: int) -> pd.DataFrame:
    """Scoring events of one season with features and label (home team won)."""
    cache = CACHE / f"{season}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    df = pd.read_csv(RAW / f"cdnnba_{season}.csv", low_memory=False,
                     usecols=["gameId", "orderNumber", "period", "clock", "scoreHome", "scoreAway"])
    df = df.sort_values(["gameId", "orderNumber"])
    g = df.groupby("gameId")
    final = g[["scoreHome", "scoreAway"]].transform("last")
    df["home_win"] = (final.scoreHome > final.scoreAway).astype(int)
    changed = (g.scoreHome.diff().fillna(0) != 0) | (g.scoreAway.diff().fillna(0) != 0)
    df = df[changed].copy()
    df["margin"] = df.scoreHome - df.scoreAway
    df["clock_seconds"] = df.clock.map(parse_clock)
    X = np.array([features(m, p, c) for m, p, c in zip(df.margin, df.period, df.clock_seconds)])
    out = pd.DataFrame(X, columns=FEATURES, index=df.index)
    out[["gameId", "period", "clock_seconds", "margin", "home_win"]] = \
        df[["gameId", "period", "clock_seconds", "margin", "home_win"]]
    out["season"] = season
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache)
    return out


def split(name: str) -> pd.DataFrame:
    return pd.concat([season_rows(s) for s in SPLITS[name]], ignore_index=True)


def main() -> None:
    tr = split("train")
    m = LogisticRegression(C=1e6, max_iter=1000).fit(tr[FEATURES], tr.home_win)
    OUT.write_text(json.dumps({
        "features": FEATURES,
        "intercept": float(m.intercept_[0]),
        "coef": [float(c) for c in m.coef_[0]],
        "trained_on": SPLITS["train"],
        "rows": len(tr),
        "games": int(tr.gameId.nunique()),
    }, indent=2))
    print(f"trained on {len(tr)} rows / {tr.gameId.nunique()} games -> {OUT}")
    print(OUT.read_text())


if __name__ == "__main__":
    main()
