"""Processor: apply GameEvent to Redis state, emit a state update, evaluate alerts.

Two delivery modes, same `process()`:
- push (PULL_SUBSCRIPTION unset): Pub/Sub POSTs each message; 2xx acks, anything else redelivers.
- pull (PULL_SUBSCRIPTION set): a StreamingPull subscriber runs inside this service; process()
  True -> ack, False/exception -> nack. Ordering keys still hold: the client hands a game's
  next message to the callback only after the previous one is acked or nacked.
Either way, DLQ after 5 delivery attempts.
"""
import base64
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import FastAPI, Response
from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.subscriber.scheduler import ThreadScheduler

from processor.alerts import evaluate, new_state
from processor.state import GameState
from processor.winprob import WinProb

STATE_TOPIC = os.environ.get("STATE_TOPIC", "")
ALERTS_TOPIC = os.environ.get("ALERTS_TOPIC", "")
REVISION = os.environ.get("K_REVISION", "local")
# T5 chaos flag: after a successful apply, NACK this fraction so Pub/Sub redelivers
FORCE_NACK_RATE = float(os.environ.get("FORCE_NACK_RATE", "0"))
PULL_SUBSCRIPTION = os.environ.get("PULL_SUBSCRIPTION", "")
PULL_THREADS = int(os.environ.get("PULL_THREADS", "64"))
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


def process(ev: dict) -> bool:
    """Apply one event end to end. True = ack it, False = make Pub/Sub redeliver it."""
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
    return not (applied and FORCE_NACK_RATE and random.random() < FORCE_NACK_RATE)


def _on_message(msg) -> None:
    try:
        ok = process(json.loads(msg.data))
    except Exception as e:  # nack: redelivered, DLQ after 5 attempts
        print(f"process failed for {msg.message_id}: {e!r}", flush=True)
        ok = False
    msg.ack() if ok else msg.nack()


@asynccontextmanager
async def lifespan(_app):
    future = None
    if PULL_SUBSCRIPTION:
        subscriber = pubsub_v1.SubscriberClient()
        future = subscriber.subscribe(
            PULL_SUBSCRIPTION, _on_message,
            flow_control=pubsub_v1.types.FlowControl(max_messages=4000),
            # default is 10 threads; each callback mostly waits on Redis/Pub/Sub I/O
            scheduler=ThreadScheduler(ThreadPoolExecutor(PULL_THREADS)))
        print(f"pulling {PULL_SUBSCRIPTION} with {PULL_THREADS} threads", flush=True)
    yield
    if future:  # SIGTERM (new revision / scale-in): stop pulling; un-acked messages get redelivered
        future.cancel()
        future.result(timeout=20)


app = FastAPI(lifespan=lifespan)


@app.post("/")
def push(body: dict) -> Response:
    # sync def: FastAPI runs it in a threadpool, so blocking Redis/Pub/Sub calls don't stall
    # the event loop and an instance serves concurrent pushes (one per game in flight).
    ok = process(json.loads(base64.b64decode(body["message"]["data"])))
    return Response(status_code=204 if ok else 500)


@app.get("/games/{game_id}")
def game(game_id: str) -> dict:
    """Current Redis state for one game (verification; service requires IAM auth)."""
    return state.get(game_id)


@app.get("/games")
def games(prefix: str) -> dict:
    """All game states whose id starts with `prefix` (benchmark verification, IAM-protected)."""
    keys = list(state.r.scan_iter(match=f"game:{prefix}*", count=1000))
    pipe = state.r.pipeline()
    for k in keys:
        pipe.hgetall(k)
    return {k.removeprefix("game:"): v for k, v in zip(keys, pipe.execute())}
