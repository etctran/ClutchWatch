"""Normalize NBA CDN play-by-play actions (live JSON or historical CSV rows) into GameEvent.

Both sources use the cdn.nba.com action schema, so one function handles both;
the caller supplies game metadata (home/away) and the source tag.
"""
import math
import re
from dataclasses import asdict, dataclass

_CLOCK = re.compile(r"PT(\d+)M([\d.]+)S")


@dataclass(frozen=True, slots=True)
class GameEvent:
    event_id: str
    game_id: str
    action_number: int
    order_number: int  # true in-game order; actionNumber is only append order
    period: int
    clock_seconds: float
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    event_type: str
    source: str
    published_at: str | None = None  # set by the publisher

    def to_dict(self) -> dict:
        return asdict(self)


def parse_clock(clock: str) -> float:
    """'PT11M58.00S' -> 718.0 seconds remaining in the period."""
    m = _CLOCK.fullmatch(clock)
    if not m:
        raise ValueError(f"bad clock: {clock!r}")
    return int(m.group(1)) * 60 + float(m.group(2))


def _str(v) -> str:
    # CSV gives NaN for blanks, JSON gives "" or missing
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def event_type(action: dict) -> str:
    t = _str(action.get("actionType")).lower()
    sub = _str(action.get("subType")).lower()
    result = _str(action.get("shotResult")).lower()
    if t in ("2pt", "3pt"):
        return "shot_made" if result == "made" else "shot_missed"
    if t == "freethrow":
        return "ft_made" if result == "made" else "ft_missed"
    if t in ("period", "game") and sub in ("start", "end"):
        return f"{t}_{sub}"
    return t or "unknown"


def normalize(action: dict, game_id: str, home: str, away: str, source: str) -> GameEvent:
    n = int(action["actionNumber"])
    gid = str(game_id).zfill(10)  # CSV stores 22400001; CDN uses "0022400001"
    return GameEvent(
        event_id=f"{gid}:{n}",
        game_id=gid,
        action_number=n,
        order_number=int(action["orderNumber"]),
        period=int(action["period"]),
        clock_seconds=parse_clock(action["clock"]),
        home_team=home,
        away_team=away,
        home_score=int(action["scoreHome"]),
        away_score=int(action["scoreAway"]),
        event_type=event_type(action),
        source=source,
    )


def infer_home_away(actions: list[dict]) -> tuple[str, str]:
    """Historical CSV has no home/away columns: the team whose basket moves scoreHome is home."""
    teams: list[str] = []
    home = None
    prev = 0
    for a in actions:
        tri = _str(a.get("teamTricode"))
        if tri and tri not in teams:
            teams.append(tri)
        sh = int(a["scoreHome"])
        if home is None and sh > prev and tri:
            home = tri
        prev = sh
    if home is None or len(teams) != 2:
        raise ValueError(f"cannot infer home/away from teams={teams}, home={home}")
    return home, next(t for t in teams if t != home)
