import json
from dataclasses import fields
from pathlib import Path

import pandas as pd
import pytest

from ingest.normalize import GameEvent, event_type, infer_home_away, normalize, parse_clock

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def hist_rows() -> list[dict]:
    # real 2024-25 game: ATL 117 @ BOS 116 (gameId 22400001)
    return pd.read_csv(FIX / "hist_22400001.csv").to_dict("records")


@pytest.fixture(scope="module")
def live_doc() -> dict:
    # real live CDN playbyplay JSON (via nba_api), finished game, trimmed to used keys
    return json.loads((FIX / "live_pbp_0022600226.json").read_text())


def test_parse_clock():
    assert parse_clock("PT12M00.00S") == 720.0
    assert parse_clock("PT00M04.30S") == pytest.approx(4.3)
    with pytest.raises(ValueError):
        parse_clock("4:30")


def test_infer_home_away(hist_rows):
    assert infer_home_away(hist_rows) == ("BOS", "ATL")


def test_historical_game(hist_rows):
    evs = [normalize(r, r["gameId"], "BOS", "ATL", "replay") for r in hist_rows]
    assert evs[0].event_id == "0022400001:2"
    assert evs[0].event_type == "period_start"
    assert evs[-1].event_type == "game_end"
    assert (evs[-1].home_score, evs[-1].away_score) == (116, 117)
    assert len({e.event_id for e in evs}) == len(evs)  # event_id is unique per game
    # replay order is orderNumber; scores never decrease in that order
    by_order = sorted(evs, key=lambda e: e.order_number)
    for a, b in zip(by_order, by_order[1:]):
        assert b.home_score >= a.home_score and b.away_score >= a.away_score
    types = {e.event_type for e in evs}
    assert {"shot_made", "shot_missed", "ft_made", "turnover", "foul", "period_end"} <= types


def test_live_game(live_doc):
    acts = live_doc["game"]["actions"]
    home, away = infer_home_away(acts)
    evs = [normalize(a, live_doc["game"]["gameId"], home, away, "live") for a in acts]
    assert evs[0].event_id == f"0022600226:{acts[0]['actionNumber']}"
    assert evs[-1].event_type == "game_end"
    assert (evs[-1].home_score, evs[-1].away_score) == (118, 108)  # live JSON scores are strings
    by_order = sorted(evs, key=lambda e: e.order_number)
    for a, b in zip(by_order, by_order[1:]):
        assert b.home_score >= a.home_score and b.away_score >= a.away_score


def test_both_sources_same_shape(hist_rows, live_doc):
    h = normalize(hist_rows[5], hist_rows[5]["gameId"], "BOS", "ATL", "replay").to_dict()
    lv = normalize(live_doc["game"]["actions"][5], "0022600226", "POR", "OKC", "live").to_dict()
    assert h.keys() == lv.keys() == {f.name for f in fields(GameEvent)}
    for k in h:
        if k != "published_at":
            assert type(h[k]) is type(lv[k]), k


def test_event_type_mapping():
    assert event_type({"actionType": "3pt", "shotResult": "Made"}) == "shot_made"
    assert event_type({"actionType": "freethrow", "shotResult": "Missed"}) == "ft_missed"
    assert event_type({"actionType": "period", "subType": "end"}) == "period_end"
    assert event_type({"actionType": "Rebound", "subType": float("nan")}) == "rebound"
