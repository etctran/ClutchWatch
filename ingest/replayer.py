"""Replay historical play-by-play to Pub/Sub.

  --speedup N      replay on the games' real timeline (timeActual), N times faster
  --target-rate R  ignore real gaps, publish at a fixed R events/s (load tests)

Games are interleaved like a real night (heap-merged by timeActual); within a game
events always go out in orderNumber order.
"""
import argparse
import heapq
import time
from datetime import datetime

import pandas as pd

from ingest.normalize import GameEvent, infer_home_away, normalize

COLS = ["gameId", "actionNumber", "orderNumber", "clock", "timeActual", "period",
        "actionType", "subType", "scoreHome", "scoreAway", "teamTricode", "shotResult"]


def load_games(csv: str, games: set[str] | None = None, limit: int | None = None
               ) -> list[list[tuple[float, GameEvent]]]:
    df = pd.read_csv(csv, usecols=COLS, low_memory=False)
    df["gid"] = df.gameId.astype(str).str.zfill(10)
    if games:
        df = df[df.gid.isin(games)]
    out = []
    for gid, g in df.groupby("gid", sort=True):
        rows = g.sort_values("orderNumber").to_dict("records")
        home, away = infer_home_away(rows)
        out.append([(datetime.fromisoformat(r["timeActual"]).timestamp(),
                     normalize(r, gid, home, away, "replay")) for r in rows])
        if limit and len(out) >= limit:
            break
    return out


def stream(games: list[list[tuple[float, GameEvent]]]):
    # merge only pops list heads, so per-game order is preserved even if timeActual is noisy
    return heapq.merge(*games, key=lambda p: p[0])


def run(games, publish, speedup: float | None = None, target_rate: float | None = None,
        max_events: int | None = None) -> int:
    start = time.monotonic()
    t0 = None
    n = 0
    for t, ev in stream(games):
        if speedup:
            t0 = t if t0 is None else t0
            delay = start + (t - t0) / speedup - time.monotonic()
        else:
            delay = start + n / target_rate - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        publish(ev)
        n += 1
        if max_events and n >= max_events:
            break
    return n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--topic", required=True, help="projects/<p>/topics/<t>")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--speedup", type=float)
    mode.add_argument("--target-rate", type=float)
    p.add_argument("--games", help="comma-separated game ids")
    p.add_argument("--limit-games", type=int)
    p.add_argument("--max-events", type=int)
    a = p.parse_args()

    from ingest.publisher import Publisher  # import here so tests don't need GCP libs/creds
    games = load_games(a.csv, set(a.games.split(",")) if a.games else None, a.limit_games)
    print(f"loaded {len(games)} games, {sum(map(len, games))} events", flush=True)
    pub = Publisher(a.topic)
    t = time.monotonic()
    n = run(games, pub.publish, a.speedup, a.target_rate, a.max_events)
    pub.flush()
    dt = time.monotonic() - t
    print(f"published={pub.ok} failed={pub.failed} sent={n} seconds={dt:.1f} rate={n / dt:.0f}/s", flush=True)


if __name__ == "__main__":
    main()
