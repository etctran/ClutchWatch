import random
from pathlib import Path

import fakeredis

from ingest.replayer import load_games
from processor.state import GameState

FIX = Path(__file__).parent / "fixtures"


def events() -> list[dict]:
    return [ev.to_dict() for _, ev in load_games(str(FIX / "hist_22400001.csv"))[0]]


def test_apply_is_idempotent():
    s = GameState(fakeredis.FakeRedis(decode_responses=True))
    evs = events()
    assert all(s.apply(e) == 2 for e in evs)  # in order: every event advances state
    assert not any(s.apply(e) for e in evs)  # full redelivery: nothing re-applied
    st = s.get("0022400001")
    assert int(st["applied"]) == len(evs) == 538
    assert (st["home_team"], st["home_score"], st["away_team"], st["away_score"]) == ("BOS", "116", "ATL", "117")


def test_redelivery_pattern_matches_source():
    # Ordered redelivery replays a suffix: deliver 0..k, then k-j..end, with 10% random repeats
    s = GameState(fakeredis.FakeRedis(decode_responses=True))
    evs = events()
    rng = random.Random(0)
    delivered = evs[:300] + evs[250:]
    delivered = [e for e in delivered for _ in range(2 if rng.random() < 0.1 else 1)]
    applied = sum(s.apply(e) > 0 for e in delivered)
    assert applied == 538
    st = s.get("0022400001")
    assert int(st["applied"]) == 538 and (st["home_score"], st["away_score"]) == ("116", "117")


def test_late_event_does_not_roll_back_score():
    s = GameState(fakeredis.FakeRedis(decode_responses=True))
    base = events()[0] | {"game_id": "g", "home_team": "H", "away_team": "A"}
    s.apply(base | {"event_id": "g:10", "order_number": 100, "home_score": 10, "away_score": 8})
    # late-entered play: new event_id, older order_number, older score
    assert s.apply(base | {"event_id": "g:11", "order_number": 50, "home_score": 7, "away_score": 8}) == 1
    st = s.get("g")
    assert (st["home_score"], st["order_number"], st["applied"]) == ("10", "100", "2")
