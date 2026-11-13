"""Pub/Sub push endpoint: send an alert to Discord once, record delivery time.

Dedup: claim `sent:<alert_id>` in Redis before sending; mark it sent after Discord 2xx.
A crash between Discord's 2xx and the mark can still double-post (claim expires after 60 s);
everything else (Pub/Sub redelivery, processor re-firing the same alert_id) is absorbed.
"""
import base64
import json
import os
from datetime import datetime, timezone

import redis
import requests
from fastapi import FastAPI, Response
from google.cloud import pubsub_v1

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
SEND = os.environ.get("NOTIFY_DISCORD", "true") == "true"  # false for bulk replays (Discord rate limits)
DELIVERIES_TOPIC = os.environ.get("DELIVERIES_TOPIC", "")
UA = "ClutchWatch (https://github.com/etctran/ClutchWatch, 0.1)"

app = FastAPI()
r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), decode_responses=True)
publisher = pubsub_v1.PublisherClient()


@app.post("/")
def push(body: dict) -> Response:
    a = json.loads(base64.b64decode(body["message"]["data"]))
    key = f"sent:{a['alert_id']}"
    if not r.set(key, "sending", nx=True, ex=60):
        # already sent -> ack; another delivery mid-send -> retry later
        return Response(status_code=204 if r.get(key) == "sent" else 503)
    status = None
    if SEND:
        try:
            resp = requests.post(WEBHOOK, json={"content": a["text"]}, headers={"User-Agent": UA}, timeout=10)
            status = resp.status_code
        except requests.RequestException as e:
            print(f"discord error {a['alert_id']}: {e!r}", flush=True)
        if status is None or not 200 <= status < 300:
            # 429 / 5xx / network: release the claim, let Pub/Sub back off and redeliver
            r.delete(key)
            print(f"discord {status} for {a['alert_id']}", flush=True)
            return Response(status_code=503)
    delivered_at = datetime.now(timezone.utc).isoformat()
    r.set(key, "sent", ex=7 * 24 * 3600)
    row = {k: a[k] for k in ("alert_id", "game_id", "rule", "published_at", "alerted_at")} | {
        "discord_status": status, "delivered_at": delivered_at, "sent_to_discord": SEND}
    publisher.publish(DELIVERIES_TOPIC, json.dumps(row).encode()).result()
    return Response(status_code=204)
