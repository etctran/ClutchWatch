"""T7: Brier score vs baselines and per-decile calibration on val (2023-24) and test (2024-25).

Uses the exported JSON through processor.winprob.WinProb, i.e. exactly what runs in prod.

  uv run --group model python -m model.evaluate
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from model.train import split
from processor.winprob import WinProb


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def calibration(p, y) -> pd.DataFrame:
    d = pd.DataFrame({"p": p, "y": y})
    d["decile"] = np.minimum((d.p * 10).astype(int), 9)
    c = d.groupby("decile").agg(pred=("p", "mean"), actual=("y", "mean"), n=("y", "size"))
    c["abs_err"] = (c.pred - c.actual).abs()
    return c


def report(name: str, df: pd.DataFrame, wp: WinProb) -> pd.DataFrame:
    p = np.array([wp.home(m, 0, per, clk) for m, per, clk in zip(df.margin, df.period, df.clock_seconds)])
    y = df.home_win.to_numpy()
    leader = np.where(df.margin > 0, 1.0, np.where(df.margin < 0, 0.0, 0.5))
    cal = calibration(p, y)
    print(f"\n== {name}: {len(df)} scoring events, {df.gameId.nunique()} games")
    print(f"Brier  model={brier(p, y):.4f}  const_0.5={brier(np.full_like(p, 0.5), y):.4f}  "
          f"leader_wins={brier(leader, y):.4f}")
    print(f"max per-decile calibration error = {cal.abs_err.max():.4f}")
    print(cal.round(4).to_string())
    return cal


def main() -> None:
    wp = WinProb()
    report("val 2023-24", split("val"), wp)
    cal = report("test 2024-25", split("test"), wp)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
    ax.plot(cal.pred, cal.actual, "o-", label="model (test 2024-25)")
    ax.set(xlabel="predicted home win prob (decile mean)", ylabel="observed home win rate",
           title="Win-prob calibration, 2024-25 test set")
    ax.legend()
    fig.savefig("model/calibration_test_2024.png", dpi=120, bbox_inches="tight")
    print("\nsaved model/calibration_test_2024.png")


if __name__ == "__main__":
    main()
