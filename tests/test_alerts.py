from pathlib import Path

from ingest.replayer import load_games
from processor.alerts import MAX_ALERTS_PER_GAME, OTHER_CAP, elapsed, evaluate, new_state
from processor.winprob import WinProb

FIX = Path(__file__).parent / "fixtures"


def ev(period, clock, home, away, gid="g"):
    return {"game_id": gid, "period": period, "clock_seconds": clock, "home_score": home,
            "away_score": away, "home_team": "BOS", "away_team": "LAL"}


def run(events, wps=None):
    st, fired = new_state(), []
    for i, e in enumerate(events):
        alerts, st = evaluate(st, e, wps[i] if wps else 0.5)
        fired += alerts
    return fired, st


def test_elapsed():
    assert elapsed(1, 720) == 0 and elapsed(4, 0) == 2880 and elapsed(5, 0) == 3180


def test_close_late_once_per_period():
    fired, _ = run([ev(4, 200, 100, 98), ev(4, 170, 100, 98), ev(4, 100, 102, 98), ev(4, 30, 102, 101),
                    ev(5, 150, 104, 104), ev(5, 60, 106, 104)])
    assert [a.rule for a in fired] == ["CLOSE_LATE", "CLOSE_LATE"]
    assert fired[0].alert_id == "g:CLOSE_LATE:4" and fired[1].alert_id == "g:CLOSE_LATE:5"
    assert "LAL @ BOS: BOS up 2 (98-100), 2:50 left in Q4." in fired[0].text


def test_close_late_not_in_q3_or_blowout():
    fired, _ = run([ev(3, 60, 80, 79), ev(4, 120, 110, 90)])
    assert fired == []


def test_wp_swing_window_and_cooldown():
    es = [ev(4, 700, 50, 50), ev(4, 600, 50, 50), ev(4, 540, 50, 50),  # 0.50 -> 0.90 in 160 s
          ev(4, 500, 50, 50),   # another big move 40 s later: in cooldown
          ev(4, 240, 50, 50),   # 0.95 but older points fell out of the 180 s window: no alert
          ev(4, 230, 50, 50)]   # 0.95 -> 0.40 within window, cooldown over: alert
    fired, _ = run(es, [0.50, 0.60, 0.90, 0.50, 0.95, 0.40])
    assert [a.rule for a in fired] == ["WP_SWING", "WP_SWING"]
    assert "swung 40 pts in the last 3 min" in fired[0].text
    assert "swung 55 pts in the last 1 min" in fired[1].text
    # a 0.30 move is below the threshold; a 0.40 move spread over > 180 s doesn't count either
    fired, _ = run([ev(4, 700, 50, 50), ev(4, 690, 50, 50)], [0.5, 0.8])
    assert fired == []
    fired, _ = run([ev(4, 700, 50, 50), ev(4, 500, 50, 50), ev(4, 300, 50, 50)], [0.5, 0.7, 0.9])
    assert fired == []


def test_no_swing_or_comeback_before_q4():
    # tuned on 2023-24: first-half swings/comebacks were most of the alerts in eventual blowouts
    fired, _ = run([ev(2, 700, 50, 50), ev(2, 600, 50, 50), ev(3, 300, 40, 60), ev(3, 100, 58, 60)],
                   [0.5, 0.9, 0.2, 0.6])
    assert fired == []


def test_comeback_once_per_team():
    # deficit built in Q2 still counts; the alert itself only fires in Q4/OT
    es = [ev(2, 600, 30, 49), ev(3, 300, 60, 62), ev(4, 300, 70, 72), ev(4, 250, 76, 72), ev(4, 190, 70, 72)]
    fired, st = run(es)
    assert [a.rule for a in fired] == ["COMEBACK"]
    assert "BOS was down 19 and is back within reach." in fired[0].text
    assert st["max_trail"]["home"] == 19
    # a 16-point hole is below the (retuned) 18-point threshold
    fired, _ = run([ev(2, 600, 30, 46), ev(4, 300, 70, 72), ev(4, 250, 76, 72)])
    assert fired == []


def test_close_late_has_a_reserved_slot():
    # Q4 swings and a comeback can use at most OTHER_CAP slots, so CLOSE_LATE still fires
    es = [ev(4, 700, 60, 80), ev(4, 690, 60, 80), ev(4, 380, 60, 80), ev(4, 370, 70, 72), ev(4, 120, 72, 72)]
    fired, st = run(es, [0.1, 0.9, 0.9, 0.1, 0.5])
    rules = [a.rule for a in fired]
    assert "CLOSE_LATE" in rules and rules.count("CLOSE_LATE") == 1
    assert len(rules) - 1 <= OTHER_CAP and st["count"] <= MAX_ALERTS_PER_GAME


def test_global_cap():
    # every event swings wildly late in a tied game: cap stops it at 4
    es = [ev(p, c, 100, 100) for p in (4, 5, 6, 7) for c in (170, 1)]
    fired, st = run(es, [0.0, 1.0] * 4)
    assert len(fired) == MAX_ALERTS_PER_GAME == st["count"]


def test_state_survives_round_trip_through_json():
    import json
    a1, st = evaluate(new_state(), ev(4, 100, 100, 99), 0.6)
    a2, _ = evaluate(json.loads(json.dumps(st)), ev(4, 90, 100, 99), 0.6)
    assert len(a1) == 1 and a2 == []  # restart between events: still deduped


def test_real_one_point_game():
    # ATL 117 @ BOS 116, 2024-25: close all the way, decided at the buzzer
    wp = WinProb()
    st, fired = new_state(), []
    for _, e in load_games(str(FIX / "hist_22400001.csv"))[0]:
        d = e.to_dict()
        alerts, st = evaluate(st, d, wp.home(d["home_score"], d["away_score"], d["period"], d["clock_seconds"]))
        fired += alerts
    rules = [a.rule for a in fired]
    assert rules.count("CLOSE_LATE") == 1
    assert len(fired) <= MAX_ALERTS_PER_GAME
    assert len({a.alert_id for a in fired}) == len(fired)
