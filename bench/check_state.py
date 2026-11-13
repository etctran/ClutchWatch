"""T5/T6: compare every game's final Redis state for a run against the source.

  uv run python -m bench.check_state <run-tag>
Checks per game: applied == source event count (no double-apply, no loss) and final score ==
source final score. Prints mismatches and a summary line.
"""
import json
import subprocess
import sys
import urllib.request

import pandas as pd

URL = "https://processor-7l2lb75w5q-uc.a.run.app"


def main() -> None:
    tag = sys.argv[1]
    token = subprocess.check_output(["gcloud", "auth", "print-identity-token"], text=True).strip()
    req = urllib.request.Request(f"{URL}/games?prefix={tag}-", headers={"Authorization": f"Bearer {token}"})
    got = json.load(urllib.request.urlopen(req, timeout=120))
    src = pd.read_csv("data/cache/source_games.csv", dtype={"game_id": str})
    bad = 0
    for r in src.itertuples():
        s = got.get(f"{tag}-{r.game_id}")
        ok = s is not None and int(s["applied"]) == r.events and \
            (int(s["home_score"]), int(s["away_score"])) == (r.home_score, r.away_score)
        if not ok:
            bad += 1
            print("MISMATCH", r.game_id, "source", r.events, r.home_score, r.away_score, "redis", s)
    print(f"tag={tag} games_in_redis={len(got)} source_games={len(src)} mismatched={bad} "
          f"applied_total={sum(int(v['applied']) for v in got.values())} source_events={src.events.sum()}")


if __name__ == "__main__":
    main()
