"""Pub/Sub push endpoint: apply GameEvent to Redis state, emit a state update.

2xx acks the message; anything else makes Pub/Sub redeliver (DLQ after 5 attempts).
"""
import base64
import json
import os
import random
from datetime import datetime, timezone

import redis
from fastapi import FastAPI, Response
from google.cloud import pubsub_v1

from processor.alerts import evaluate, new_state
from processor.state import GameState
from processor.winprob import WinProb

STATE_TOPIC = os.environ.get("STATE_TOPIC", "")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC", "")
REVISION = os.environ.get("K_REVISION", "local")
# T5 chaos flag: after a successful apply, NACK this fraction so Pub/Sub redelivers
FORCE_NACK_RATE = float(os.environ.get("FORCE_NACK_RATE", "0"))

app = FastAPI()
wp = WinProb()
state = GameState(redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), decode_responses=True))
publisher = pubsub_v1.PublisherClient(
    batch_settings=pubsub_v1.types.BatchSettings(max_messages=500, max_latency=0.005))


def state_row(ev: dict, applied: bool, home_wp: float) -> dict:
    # Built from the event itself (scores are absolute), so a redelivered event yields the
    # same row; wp_timeline is read with DISTINCT event_id / MIN(processed_at).
    return {k: ev[k] for k in ("event_id", "game_id", "order_number", "period", "clock_seconds",
                               "home_team", "away_team", "home_score", "away_score",
                               "event_type", "source", "published_at")} | {
        "home_wp": home_wp,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "duplicate": not applied,
        "revision": REVISION,
    }


@app.post("/")
def push(body: dict) -> Response:
    # sync def: FastAPI runs it in a threadpool, so blocking Redis/Pub/Sub calls don't stall
    # the event loop and an instance serves concurrent pushes (one per game in flight).
    ev = json.loads(base64.b64decode(body["message"]["data"]))
    result = state.apply(ev)
    applied = result > 0
    home_wp = wp.home(ev["home_score"], ev["away_score"], ev["period"], ev["clock_seconds"])
    row = state_row(ev, applied, home_wp)
    # Publish even for duplicates: if we crashed after the Redis apply but before this
    # publish, the redelivery is the only chance to get the row out.
    futures = [publisher.publish(STATE_TOPIC, json.dumps(row).encode())]
    if result == 2:  # only events that advance the game drive alerts (not late-entered plays)
        alerts, st = evaluate(state.alert_state(ev["game_id"]) or new_state(), ev, home_wp)
        for a in alerts:
            msg = {"alert_id": a.alert_id, "game_id": a.game_id, "rule": a.rule, "text": a.text,
                   "event_id": ev["event_id"], "home_wp": home_wp,
                   "published_at": ev["published_at"], "alerted_at": row["processed_at"]}
            futures.append(publisher.publish(ALERTS_TOPIC, json.dumps(msg).encode()))
    for f in futures:
        f.result()
    if result == 2:
        # Saved only after alerts are published: a crash in between re-fires on the next event
        # with the same alert_id (deterministic), which the notifier dedups. Saving first could
        # lose the alert.
        state.save_alert_state(ev["game_id"], st)
    if applied and FORCE_NACK_RATE and random.random() < FORCE_NACK_RATE:
        return Response(status_code=500)
    return Response(status_code=204)


@app.get("/games/{game_id}")
def game(game_id: str) -> dict:
    """Current Redis state for one game (verification; service requires IAM auth)."""
    return state.get(game_id)
