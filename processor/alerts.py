"""Alert rules. `evaluate` is pure: (per-game alert state, event, home WP) -> (alerts, new state).

State is a small JSON blob per game in Redis, so dedup survives processor restarts.
Ordered push keeps one message in flight per game, so there is no concurrent writer per game.
"""
import json
from dataclasses import dataclass

CLOSE_LATE_SECONDS, CLOSE_LATE_MARGIN = 180, 5
SWING_WP, SWING_WINDOW, SWING_COOLDOWN = 0.35, 180, 300  # spec: 0.25; retuned, see DECISIONS
COMEBACK_DEFICIT, COMEBACK_WITHIN = 18, 3  # spec: 15; retuned, see DECISIONS
MAX_ALERTS_PER_GAME = 4
# Tuning knobs (spec values: 1, 1, 4). Chosen values come from bench/tune_alerts.py on
# 2023-24 only; see docs/DECISIONS.md. 2024-25 stays the held-out test season.
SWING_MIN_PERIOD = 4
COMEBACK_MIN_PERIOD = 4
OTHER_CAP = 2  # non-CLOSE_LATE alerts may use at most this many of the MAX_ALERTS_PER_GAME slots


@dataclass(frozen=True)
class Alert:
    alert_id: str  # deterministic, so a re-evaluation can't create a second distinct alert
    game_id: str
    rule: str
    text: str


def elapsed(period: int, clock: float) -> float:
    """Game seconds elapsed (regulation 4x720, then 300 per OT)."""
    if period <= 4:
        return (period - 1) * 720 + (720 - clock)
    return 2880 + (period - 5) * 300 + (300 - clock)


def period_name(p: int) -> str:
    return f"Q{p}" if p <= 4 else ("OT" if p == 5 else f"{p - 4}OT")


def situation(ev: dict) -> str:
    m = ev["home_score"] - ev["away_score"]
    lead = "tied" if m == 0 else f"{ev['home_team'] if m > 0 else ev['away_team']} up {abs(m)}"
    mins, secs = divmod(int(ev["clock_seconds"]), 60)
    return (f"🏀 {ev['away_team']} @ {ev['home_team']}: {lead} "
            f"({ev['away_score']}-{ev['home_score']}), {mins}:{secs:02d} left in {period_name(ev['period'])}.")


def new_state() -> dict:
    return {"count": 0, "fired": [], "last_swing": None, "wp": [], "max_trail": {"home": 0, "away": 0}}


def evaluate(st: dict, ev: dict, wp: float) -> tuple[list[Alert], dict]:
    st = json.loads(json.dumps(st))  # don't mutate the caller's copy
    gid, per, clock = ev["game_id"], ev["period"], ev["clock_seconds"]
    t = elapsed(per, clock)
    m = ev["home_score"] - ev["away_score"]
    out: list[tuple[str, str, str]] = []  # (dedup key, rule, detail)

    # CLOSE_LATE: Q4/OT, <= 3:00 left, within 5. Once per game per period.
    if per >= 4 and clock <= CLOSE_LATE_SECONDS and abs(m) <= CLOSE_LATE_MARGIN:
        out.append((f"CLOSE_LATE:{per}", "CLOSE_LATE", "Close game late."))

    # WP_SWING: |dWP| >= 0.25 vs any point in the last 180 game-seconds. 5-game-minute cooldown.
    st["wp"] = [p for p in st["wp"] if t - p[0] <= SWING_WINDOW] + [[t, wp]]
    swing = max(st["wp"], key=lambda p: abs(wp - p[1]))
    cooled = st["last_swing"] is None or t - st["last_swing"] >= SWING_COOLDOWN
    if per >= SWING_MIN_PERIOD and abs(wp - swing[1]) >= SWING_WP and cooled:
        mins = max(1, round((t - swing[0]) / 60))
        out.append((f"WP_SWING:{int(t)}", "WP_SWING",
                    f"Home win prob swung {round(abs(wp - swing[1]) * 100)} pts in the last {mins} min."))

    # COMEBACK: a team that trailed by >= 15 is now within 3 or leading. Once per team.
    st["max_trail"]["home"] = max(st["max_trail"]["home"], -m)
    st["max_trail"]["away"] = max(st["max_trail"]["away"], m)
    for side, team, now_behind in (("home", ev["home_team"], -m), ("away", ev["away_team"], m)):
        if per >= COMEBACK_MIN_PERIOD and st["max_trail"][side] >= COMEBACK_DEFICIT \
                and now_behind <= COMEBACK_WITHIN:
            out.append((f"COMEBACK:{side}", "COMEBACK",
                        f"{team} was down {st['max_trail'][side]} and "
                        + ("now leads." if now_behind < 0 else "is back within reach.")))

    alerts = []
    for key, rule, detail in out:
        if key.startswith("WP_SWING") or key not in st["fired"]:
            cap = MAX_ALERTS_PER_GAME if rule == "CLOSE_LATE" else OTHER_CAP
            if st["count"] >= cap:
                continue
            st["count"] += 1
            if rule == "WP_SWING":
                st["last_swing"] = t
            else:
                st["fired"].append(key)
            alerts.append(Alert(f"{gid}:{key}", gid, rule, f"{situation(ev)} {detail}"))
    return alerts, st
