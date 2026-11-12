"""Publish GameEvents to Pub/Sub with ordering_key = game_id."""
import json
import threading
from dataclasses import replace
from datetime import datetime, timezone

from google.cloud import pubsub_v1

from ingest.normalize import GameEvent


class Publisher:
    def __init__(self, topic: str, max_latency: float = 0.01):
        self.client = pubsub_v1.PublisherClient(
            batch_settings=pubsub_v1.types.BatchSettings(max_messages=500, max_latency=max_latency),
            publisher_options=pubsub_v1.types.PublisherOptions(enable_message_ordering=True),
        )
        self.topic = topic
        self.ok = 0
        self.failed = 0
        self._lock = threading.Lock()
        self._done = threading.Condition(self._lock)
        self._pending = 0

    def publish(self, ev: GameEvent) -> None:
        ev = replace(ev, published_at=datetime.now(timezone.utc).isoformat())
        data = json.dumps(ev.to_dict()).encode()
        with self._lock:
            self._pending += 1
        fut = self.client.publish(self.topic, data, ordering_key=ev.game_id)
        fut.add_done_callback(lambda f, key=ev.game_id: self._on_done(f, key))

    def _on_done(self, fut, key: str) -> None:
        err = fut.exception()
        with self._lock:
            if err is None:
                self.ok += 1
            else:
                self.failed += 1
            self._pending -= 1
            self._done.notify_all()
        if err is not None:
            # an ordered key pauses after a failure; resume so later events still flow.
            # The failed event is counted and will show up as loss in T4.
            print(f"publish failed for {key}: {err!r}", flush=True)
            self.client.resume_publish(self.topic, key)

    def flush(self) -> None:
        with self._lock:
            self._done.wait_for(lambda: self._pending == 0)
