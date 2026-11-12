from pathlib import Path

from ingest.live_poller import new_actions
from ingest.replayer import load_games, run

FIX = Path(__file__).parent / "fixtures"


def a(num: int, order: int) -> dict:
    return {"actionNumber": num, "orderNumber": order}


def test_new_actions_cursor():
    acts = [a(2, 20), a(4, 40), a(7, 70)]
    fresh, cur = new_actions(acts, 0)
    assert [x["actionNumber"] for x in fresh] == [2, 4, 7] and cur == 7
    assert new_actions(acts, cur) == ([], 7)  # nothing new on re-poll
    # late-entered play: higher actionNumber, earlier orderNumber -> picked up, in game order
    acts += [a(9, 90), a(8, 50)]
    fresh, cur = new_actions(acts, 7)
    assert [x["actionNumber"] for x in fresh] == [8, 9] and cur == 9


def test_replayer_publishes_full_game_in_order():
    games = load_games(str(FIX / "hist_22400001.csv"))
    assert len(games) == 1 and len(games[0]) == 538
    sent = []
    n = run(games, sent.append, target_rate=1e9)
    assert n == 538
    assert [e.order_number for e in sent] == sorted(e.order_number for e in sent)
    assert (sent[-1].home_team, sent[-1].away_team) == ("BOS", "ATL")
    assert (sent[-1].home_score, sent[-1].away_score) == (116, 117)
