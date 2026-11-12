"""Live poller: every 5 s, publish play-by-play actions we haven't seen yet for each live game.

Runs as a Cloud Run service (needs CPU always allocated: --no-cpu-throttling) with a
health endpoint; the poll loop runs in a background thread.
"""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from ingest.normalize import normalize

POLL_SECONDS = 5
LIVE, FINAL = 2, 3  # scoreboard gameStatus


def new_actions(actions: list[dict], cursor: int) -> tuple[list[dict], int]:
    """Actions with actionNumber > cursor, in game order (orderNumber), plus the new cursor.

    actionNumber is append order, so a late-entered play still gets a higher number and is
    picked up. ponytail: edits to an already-published action (same actionNumber) are not
    re-sent; add an `edited`-timestamp diff if corrections matter.
    """
    fresh = sorted((a for a in actions if int(a["actionNumber"]) > cursor),
                   key=lambda a: int(a["orderNumber"]))
    return fresh, max([cursor, *(int(a["actionNumber"]) for a in fresh)])


def poll_forever(publish) -> None:
    from nba_api.live.nba.endpoints import playbyplay, scoreboard

    # ponytail: in-memory cursors; a restart republishes each live game from the start,
    # which the processor's idempotency (SET NX on event_id) absorbs.
    cursors: dict[str, int] = {}
    done: set[str] = set()
    while True:
        t = time.monotonic()
        try:
            games = scoreboard.ScoreBoard().get_dict()["scoreboard"]["games"]
        except Exception as e:  # CDN hiccup: skip this tick
            print(f"scoreboard error: {e!r}", flush=True)
            games = []
        for g in games:
            gid = g["gameId"]
            if g["gameStatus"] not in (LIVE, FINAL) or gid in done:
                continue
            try:
                acts = playbyplay.PlayByPlay(gid).get_dict()["game"]["actions"]
            except Exception as e:
                print(f"pbp error {gid}: {e!r}", flush=True)
                continue
            fresh, cursors[gid] = new_actions(acts, cursors.get(gid, 0))
            home, away = g["homeTeam"]["teamTricode"], g["awayTeam"]["teamTricode"]
            for a in fresh:
                publish(normalize(a, gid, home, away, "live"))
            if fresh:
                print(f"{gid} {away}@{home}: +{len(fresh)} (cursor {cursors[gid]})", flush=True)
            if g["gameStatus"] == FINAL and any(a.get("actionType") == "game" for a in acts):
                done.add(gid)
        time.sleep(max(0.0, POLL_SECONDS - (time.monotonic() - t)))


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


def main() -> None:
    from ingest.publisher import Publisher

    pub = Publisher(os.environ["TOPIC"])
    threading.Thread(target=poll_forever, args=(pub.publish,), daemon=True).start()
    HTTPServer(("", int(os.environ.get("PORT", 8080))), Health).serve_forever()


if __name__ == "__main__":
    main()
